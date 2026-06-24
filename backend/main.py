import os
import sys
import glob

# Prevent loading incompatible system-wide CUDA DLLs by filtering them from PATH and environment on Windows
if os.name == 'nt':
    for k in list(os.environ.keys()):
        if "CUDA_PATH" in k.upper():
            os.environ.pop(k, None)
    _paths = os.environ.get("PATH", "").split(";")
    _filtered = [p for p in _paths if "NVIDIA GPU Computing Toolkit" not in p]
    os.environ["PATH"] = ";".join(_filtered)

    # Automatically resolve the virtual environment path and add its NVIDIA/Torch binaries to the DLL search directories
    try:
        venv_root = os.path.dirname(os.path.dirname(sys.executable))
        nvidia_dirs = glob.glob(os.path.join(venv_root, "Lib", "site-packages", "nvidia", "*", "bin"))
        for d in nvidia_dirs:
            if os.path.exists(d):
                os.add_dll_directory(d)
        
        torch_lib = os.path.join(venv_root, "Lib", "site-packages", "torch", "lib")
        if os.path.exists(torch_lib):
            os.add_dll_directory(torch_lib)
            
        # Pre-import torch to force loading of the correct cuDNN/CUDA DLLs first
        import torch
        print(f"[DLL Isolation] PyTorch pre-loaded. CUDA available: {torch.cuda.is_available()}")
    except Exception as dll_err:
        print(f"[DLL Isolation Warning] Failed to configure isolated DLL paths: {dll_err}")



from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

# Log API Key status on startup
_api_key = os.getenv("GEMINI_API_KEY")
if _api_key:
    _masked = _api_key[:4] + "..." + _api_key[-4:] if len(_api_key) > 8 else "..."
    print(f"[Startup] Gemini API Key loaded: {_masked} (length: {len(_api_key)})")
else:
    print("[Startup] WARNING: Gemini API Key is missing or empty in environment!")

import uuid
import asyncio
import shutil
from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from typing import List, Dict

import models
from database import get_db, engine, SessionLocal
from tasks import task_ingest_and_scraping, task_synthesize_tts_segment, dispatch_task

# Initialize FastAPI app
app = FastAPI(title="AI Video Translation Dashboard API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Try to find the built frontend path
packaged_dist = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")
packaged_out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
local_dist = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../frontend/dist"))
local_out = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../frontend/out"))

frontend_dir = None
if os.path.exists(packaged_dist) and os.path.exists(os.path.join(packaged_dist, "index.html")):
    frontend_dir = packaged_dist
elif os.path.exists(packaged_out) and os.path.exists(os.path.join(packaged_out, "index.html")):
    frontend_dir = packaged_out
elif os.path.exists(local_dist) and os.path.exists(os.path.join(local_dist, "index.html")):
    frontend_dir = local_dist
elif os.path.exists(local_out) and os.path.exists(os.path.join(local_out, "index.html")):
    frontend_dir = local_out


if not frontend_dir:
    @app.get("/")
    async def root():
        return {"status": "running", "service": "Video Translation Orchestrator API", "docs": "/docs"}

@app.get("/app")
async def app_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/")



DATA_DIR = "/app/data" if os.path.exists("/app") else "./data"
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

@app.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    safe_filename = os.path.basename(file.filename)
    file_path = os.path.join(UPLOADS_DIR, safe_filename)
    
    # Write file in chunks to avoid memory issues with large videos
    with open(file_path, "wb") as buffer:
        while True:
            chunk = await file.read(1024 * 1024)  # 1MB chunks
            if not chunk:
                break
            buffer.write(chunk)
            
    return {"filename": file_path, "status": "uploaded"}


# Connection manager for WebSockets
class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, project_id: str, websocket: WebSocket):
        await websocket.accept()
        if project_id not in self.active_connections:
            self.active_connections[project_id] = []
        self.active_connections[project_id].append(websocket)
        print(f"[WebSocket] Connected client to project {project_id}")

    def disconnect(self, project_id: str, websocket: WebSocket):
        if project_id in self.active_connections:
            self.active_connections[project_id].remove(websocket)
            if not self.active_connections[project_id]:
                del self.active_connections[project_id]
        print(f"[WebSocket] Disconnected client from project {project_id}")

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        await websocket.send_json(message)

    async def broadcast_project_status(self, project_id: str, message: dict):
        if project_id in self.active_connections:
            for connection in self.active_connections[project_id]:
                try:
                    await connection.send_json(message)
                except WebSocketDisconnect:
                    print(f"[WebSocket] Client disconnected during broadcast, will be removed.")
                except Exception as e:
                    print(f"[WebSocket] Broadcast error to a client: {e}")

ws_manager = WebSocketManager()

@app.websocket("/ws/progress/{project_id}")
async def websocket_progress(websocket: WebSocket, project_id: str):
    await websocket.accept()
    await websocket.close(code=1000)

@app.post("/api/projects")
async def create_project(
    payload: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Creates a new project record and schedules ingestion.
    """
    input_type = payload.get("input_type")
    input_source = payload.get("input_source")
    source_language = payload.get("source_language", "en")
    target_language = payload.get("target_language", "km")
    genre_mode = payload.get("genre_mode", "anime_recap")
    narrator_voice = payload.get("narrator_voice", "male")
    enable_background_sound = payload.get("enable_background_sound", True)
    enable_noise_cleaning = payload.get("enable_noise_cleaning", True)
    enable_subtitles = payload.get("enable_subtitles", True)
    tts_engine = payload.get("tts_engine", "voxcpm2")
    generate_shorts = payload.get("generate_shorts", False)

    if not input_type or not input_source:
        raise HTTPException(status_code=400, detail="Missing required parameters")

    # Only keep 1 video: delete all existing projects first to free up storage
    existing_projects = db.query(models.Project).all()
    for p in existing_projects:
        db.delete(p)
        project_dir = os.path.join(DATA_DIR, p.id)
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir, ignore_errors=True)
    db.commit()

    project_id = str(uuid.uuid4())
    project_name = os.path.basename(input_source) if input_type == "local" else f"remote_stream_{project_id[:8]}"

    new_project = models.Project(
        id=project_id,
        name=project_name,
        input_type=input_type,
        input_source=input_source,
        source_language=source_language,
        target_language=target_language,
        genre_mode=genre_mode,
        narrator_voice=narrator_voice,
        enable_background_sound=enable_background_sound,
        enable_noise_cleaning=enable_noise_cleaning,
        enable_subtitles=enable_subtitles,
        tts_engine=tts_engine,
        generate_shorts=generate_shorts,
        status="pending"
    )

    db.add(new_project)
    db.commit()
    db.refresh(new_project)

    # Trigger Queue 0: Ingest & Smart Scraping via Celery
    dispatch_task(task_ingest_and_scraping, project_id, background_tasks=background_tasks)

    return {
        "message": "Project created and pipeline started",
        "project_id": project_id,
        "name": project_name,
        "status": "pending"
    }

@app.get("/api/projects")
async def list_projects(db: Session = Depends(get_db)):
    projects = db.query(models.Project).order_by(models.Project.created_at.desc()).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "status": p.status,
            "genre_mode": p.genre_mode,
            "created_at": p.created_at.isoformat()
        } for p in projects
    ]

@app.get("/api/projects/{project_id}")
async def get_project_details(project_id: str, db: Session = Depends(get_db)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    chunks = db.query(models.VideoChunk).filter(models.VideoChunk.project_id == project_id).order_by(models.VideoChunk.chunk_index).all()
    segments = db.query(models.Segment).filter(models.Segment.project_id == project_id).order_by(models.Segment.segment_index).all()
    thumbnails = db.query(models.Thumbnail).filter(models.Thumbnail.project_id == project_id).order_by(models.Thumbnail.score.desc()).all()

    total_chunks = len(chunks)
    completed_chunks = sum(1 for c in chunks if c.status == "completed")
    total_segments = len(segments)
    completed_segments = sum(1 for s in segments if s.status == "synthesized")

    progress_percentage = 0
    if project.status == "completed":
        progress_percentage = 100
    elif project.status == "exporting":
        progress_percentage = 90
    elif project.status == "synthesizing":
        progress_percentage = 50 + int((completed_segments / max(1, total_segments)) * 40)
    elif project.status == "translating":
        progress_percentage = 40
    elif project.status == "transcribing":
        progress_percentage = 30
    elif project.status == "stemming":
        progress_percentage = 20
    elif project.status == "ingesting":
        progress_percentage = 10

    project_dir = os.path.join(DATA_DIR, project.id)
    prompts_file_path = os.path.join(project_dir, "manual_prompts.txt")
    manual_prompts_file = os.path.abspath(prompts_file_path) if os.path.exists(prompts_file_path) else None

    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "input_type": project.input_type,
            "input_source": project.input_source,
            "source_language": project.source_language,
            "target_language": project.target_language,
            "genre_mode": project.genre_mode,
            "narrator_voice": project.narrator_voice,
            "enable_background_sound": project.enable_background_sound,
            "enable_noise_cleaning": getattr(project, "enable_noise_cleaning", True),
            "enable_subtitles": getattr(project, "enable_subtitles", True),
            "tts_engine": getattr(project, "tts_engine", "voxcpm2"),
            "generate_shorts": project.generate_shorts,
            "manual_prompts_file": manual_prompts_file,
            "status": project.status,
            "progress": progress_percentage,
            "output_video_16_9": project.output_video_16_9,
            "output_video_9_16": project.output_video_9_16,
            "created_at": project.created_at.isoformat(),
            "updated_at": project.updated_at.isoformat()
        },
        "chunks": [
            {
                "index": c.chunk_index,
                "status": c.status,
                "error": c.error_traceback
            } for c in chunks
        ],
        "segments": [
            {
                "id": s.id,
                "chunk_index": s.chunk_index,
                "segment_index": s.segment_index,
                "speaker_id": s.speaker_id,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "original_text": s.original_text,
                "translated_text": s.translated_text,
                "ai_prompt": s.ai_prompt,
                "detected_voice_type": s.detected_voice_type,
                "status": s.status,
                "error": s.error_traceback
            } for s in segments
        ],
        "thumbnails": [
            {
                "id": t.id,
                "filename": os.path.basename(t.path),
                "score": t.score,
                "timestamp": t.timestamp
            } for t in thumbnails
        ]
    }


@app.put("/api/projects/{project_id}")
async def update_project_settings(
    project_id: str,
    payload: dict,
    db: Session = Depends(get_db)
):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if "narrator_voice" in payload:
        project.narrator_voice = payload["narrator_voice"]
    if "genre_mode" in payload:
        project.genre_mode = payload["genre_mode"]
    if "enable_background_sound" in payload:
        project.enable_background_sound = payload["enable_background_sound"]
    if "enable_noise_cleaning" in payload:
        project.enable_noise_cleaning = payload["enable_noise_cleaning"]
    if "enable_subtitles" in payload:
        project.enable_subtitles = payload["enable_subtitles"]
    if "tts_engine" in payload:
        project.tts_engine = payload["tts_engine"]
    if "generate_shorts" in payload:
        project.generate_shorts = payload["generate_shorts"]

    db.commit()
    return {"message": "Project settings updated successfully"}


@app.put("/api/projects/{project_id}/segments/{segment_id}")
async def update_segment(
    project_id: str,
    segment_id: int,
    payload: dict,
    db: Session = Depends(get_db)
):
    segment = db.query(models.Segment).filter(
        models.Segment.project_id == project_id,
        models.Segment.id == segment_id
    ).first()

    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    translated_text = payload.get("translated_text")
    speaker_id = payload.get("speaker_id")

    if translated_text is None and speaker_id is None:
        raise HTTPException(status_code=400, detail="Missing parameters to update")

    if translated_text is not None:
        segment.translated_text = translated_text
    if speaker_id is not None:
        segment.speaker_id = speaker_id

    segment.status = "translated"
    db.commit()

    return {
        "message": "Segment updated",
        "segment_id": segment_id,
        "translated_text": segment.translated_text,
        "speaker_id": segment.speaker_id
    }

@app.post("/api/projects/{project_id}/segments/{segment_id}/render")
async def render_segment(
    project_id: str,
    segment_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    segment = db.query(models.Segment).filter(
        models.Segment.project_id == project_id,
        models.Segment.id == segment_id
    ).first()

    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    dispatch_task(task_synthesize_tts_segment, project_id, segment_id, background_tasks=background_tasks)
    return {"message": "Segment re-rendering scheduled", "segment_id": segment_id}


@app.post("/api/projects/{project_id}/segments/batch-translate")
async def batch_translate_segments(
    project_id: str,
    payload: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Accept manual translations for segments that failed API quota.
    Dispatches TTS synthesis for each successfully translated segment.
    """
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    translations = payload.get("translations", [])
    if not translations:
        raise HTTPException(status_code=400, detail="No translations provided")

    success_count = 0
    errors = []

    for item in translations:
        segment_id = item.get("segment_id")
        translated_text = item.get("translated_text", "").strip()

        if not segment_id or not translated_text:
            errors.append({"segment_id": segment_id, "error": "Missing segment_id or translated_text"})
            continue

        segment = db.query(models.Segment).filter(
            models.Segment.project_id == project_id,
            models.Segment.id == segment_id
        ).first()

        if not segment:
            errors.append({"segment_id": segment_id, "error": "Segment not found"})
            continue

        segment.translated_text = translated_text
        segment.status = "translated"
        segment.ai_prompt = None  # Clear the prompt since translation is now provided
        db.commit()

        success_count += 1

    if success_count > 0:
        # Check if ALL segments in the project are translated
        all_segments = db.query(models.Segment).filter(models.Segment.project_id == project_id).all()
        all_translated = all(s.translated_text for s in all_segments)
        
        if all_translated:
            project.status = "synthesizing"
            db.commit()
            
            # Dispatch TTS for all translated segments now
            for s in all_segments:
                if s.status == "translated":
                    dispatch_task(task_synthesize_tts_segment, project_id, s.id, background_tasks=background_tasks)

    return {
        "message": f"Batch translation completed",
        "success_count": success_count,
        "error_count": len(errors),
        "errors": errors
    }


import json

def get_default_voice_mapping(db: Session, project_id: str) -> dict:
    segments = db.query(models.Segment).filter(models.Segment.project_id == project_id).all()
    mapping = {}
    for seg in segments:
        spk = seg.speaker_id or "Speaker_Female"
        if spk not in mapping:
            detected = seg.detected_voice_type or "female"
            # Default rate/pitch adjustments
            rate = "+0%"
            pitch = "+0Hz"
            if detected == "elder_male":
                rate = "-2%"
                pitch = "-4Hz"
            elif detected == "elder_female":
                rate = "-2%"
                pitch = "-2Hz"
            elif detected == "male":
                rate = "+4%"
                pitch = "-2Hz"
            elif detected == "kid":
                rate = "+2%"
                pitch = "+4Hz"
            
            mapping[spk] = {
                "voice": detected,
                "rate": rate,
                "pitch": pitch
            }
    return mapping


@app.get("/api/projects/{project_id}/voice-mapping")
async def get_project_voice_mapping(project_id: str, db: Session = Depends(get_db)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project_dir = os.path.join(DATA_DIR, project_id)
    voice_mapping_path = os.path.join(project_dir, "voice_mapping.json")

    mapping = {}
    if os.path.exists(voice_mapping_path):
        try:
            with open(voice_mapping_path, "r", encoding="utf-8") as f:
                mapping = json.load(f)
        except Exception:
            mapping = {}

    # If mapping is empty or missing speakers, populate them automatically
    default_map = get_default_voice_mapping(db, project_id)
    updated = False
    for spk, config in default_map.items():
        if spk not in mapping:
            mapping[spk] = config
            updated = True

    if updated or not os.path.exists(voice_mapping_path):
        os.makedirs(project_dir, exist_ok=True)
        try:
            with open(voice_mapping_path, "w", encoding="utf-8") as f:
                json.dump(mapping, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving default voice mapping: {e}")

    return mapping


@app.post("/api/projects/{project_id}/voice-mapping")
async def update_project_voice_mapping(project_id: str, payload: dict, db: Session = Depends(get_db)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project_dir = os.path.join(DATA_DIR, project_id)
    voice_mapping_path = os.path.join(project_dir, "voice_mapping.json")

    mapping = {}
    if os.path.exists(voice_mapping_path):
        try:
            with open(voice_mapping_path, "r", encoding="utf-8") as f:
                mapping = json.load(f)
        except Exception:
            pass

    # Update mapping with incoming payload
    for spk, config in payload.items():
        if isinstance(config, dict):
            mapping[spk] = {
                "voice": config.get("voice", "female"),
                "rate": config.get("rate", "+0%"),
                "pitch": config.get("pitch", "+0Hz")
            }

    # Save mapping
    os.makedirs(project_dir, exist_ok=True)
    try:
        with open(voice_mapping_path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2, ensure_ascii=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save voice mapping: {e}")

    # Set status of affected segments back to 'translated' so they get re-rendered with new voices
    updated_speakers = list(payload.keys())
    segments = db.query(models.Segment).filter(
        models.Segment.project_id == project_id,
        models.Segment.speaker_id.in_(updated_speakers)
    ).all()
    for seg in segments:
        if seg.status == "synthesized":
            seg.status = "translated"
    db.commit()

    return {"message": "Voice mapping updated", "mapping": mapping}


@app.get("/preview_tts")
@app.get("/api/preview_tts")
async def preview_tts(
    text: str,
    voice: str,
    target_lang: str = "km",
    voice_tone: str = "auto",
    translation_style: str = "cinematic"
):
    # Determine TTS backend
    tts_backend = os.getenv("TTS_BACKEND", "voxcpm2").strip().lower()
    
    # Create a temporary file path
    temp_dir = os.path.join(DATA_DIR, "temp_previews")
    os.makedirs(temp_dir, exist_ok=True)
    
    # Self-clean old preview files (> 5 minutes)
    import time
    now = time.time()
    for f in os.listdir(temp_dir):
        fp = os.path.join(temp_dir, f)
        if os.path.isfile(fp) and now - os.path.getmtime(fp) > 300:
            try:
                os.remove(fp)
            except Exception:
                pass
                
    temp_filename = f"preview_{uuid.uuid4().hex}.wav"
    output_wav = os.path.join(temp_dir, temp_filename)
    
    try:
        # Determine voice config
        effective_voice_type = voice
        
        if tts_backend == "voxcpm2":
            import sys
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
            import voxcpm2
            profile = "female"
            if effective_voice_type in ("male", "elder_male"):
                profile = "male"
            elif effective_voice_type == "kid":
                profile = "kid"
                
            voxcpm2.generate(
                text=text,
                output_path=output_wav,
                voice_profile=profile,
                target_lang=target_lang
            )
        else:
            # Edge-TTS
            voice_profiles = {
                "male": {"voice": "km-KH-PisethNeural", "rate": "+0%", "pitch": "+0Hz"},
                "female": {"voice": "km-KH-SreymomNeural", "rate": "+0%", "pitch": "+0Hz"},
                "kid": {"voice": "km-KH-SreymomNeural", "rate": "+5%", "pitch": "+6Hz"},
                "elder_male": {"voice": "km-KH-PisethNeural", "rate": "-2%", "pitch": "-4Hz"},
                "elder_female": {"voice": "km-KH-SreymomNeural", "rate": "-2%", "pitch": "-2Hz"},
            }
            voice_config = voice_profiles.get(effective_voice_type, voice_profiles["female"])
            
            import subprocess
            edge_cmd = [
                "edge-tts",
                "--voice", voice_config["voice"],
                "--rate", voice_config["rate"],
                "--pitch", voice_config["pitch"],
                "--text", text,
                "--write-media", output_wav
            ]
            subprocess.run(edge_cmd, capture_output=True)
            
        if os.path.exists(output_wav) and os.path.getsize(output_wav) > 0:
            return FileResponse(output_wav, media_type="audio/wav")
        else:
            raise HTTPException(status_code=500, detail="Failed to generate TTS preview")
    except Exception as e:
        print(f"[Preview TTS Error] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_id}/segments/export-prompts")
async def export_translation_prompts(
    project_id: str,
    db: Session = Depends(get_db)
):
    """
    Returns all segments that need manual translation with pre-built AI prompts.
    """
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    segments = db.query(models.Segment).filter(
        models.Segment.project_id == project_id,
        models.Segment.status == "needs_manual_translation"
    ).order_by(models.Segment.segment_index).all()

    project_dir = os.path.join(DATA_DIR, project_id)
    prompts_file_path = os.path.join(project_dir, "manual_prompts.txt")
    manual_prompts_file = os.path.abspath(prompts_file_path) if os.path.exists(prompts_file_path) else None

    return {
        "project_id": project_id,
        "total_segments_needing_translation": len(segments),
        "manual_prompts_file": manual_prompts_file,
        "segments": [
            {
                "segment_id": s.id,
                "segment_index": s.segment_index,
                "speaker_id": s.speaker_id,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "original_text": s.original_text,
                "ai_prompt": s.ai_prompt
            } for s in segments
        ]
    }

@app.get("/api/downloads/{project_id}/video/{format}")
async def download_video(project_id: str, format: str, db: Session = Depends(get_db)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project_dir = os.path.join(DATA_DIR, project_id)
    file_path = None

    if format == "original":
        file_path = os.path.join(project_dir, "source_video.mp4")
    elif format == "16_9":
        file_path = os.path.join(project_dir, "output_16_9.mp4")
    elif format == "9_16":
        file_path = os.path.join(project_dir, "output_9_16.mp4")

    if file_path and os.path.exists(file_path):
        return FileResponse(file_path, media_type="video/mp4")
    raise HTTPException(status_code=404, detail=f"Video format {format} not found")

@app.get("/api/downloads/{project_id}/audio/{format}")
async def download_audio(project_id: str, format: str, db: Session = Depends(get_db)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project_dir = os.path.join(DATA_DIR, project_id)
    
    if format in ["mp3", "wav"]:
        file_path = os.path.join(project_dir, "final_dubbed_audio.wav")
        if os.path.exists(file_path):
            return FileResponse(file_path, media_type="audio/wav")
    
    raise HTTPException(status_code=404, detail=f"Audio format {format} not found")

@app.get("/api/downloads/{project_id}/subtitles/{format}")
async def download_subtitles(project_id: str, format: str, db: Session = Depends(get_db)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project_dir = os.path.join(DATA_DIR, project_id)
    
    if format == "srt":
        file_path = os.path.join(project_dir, "subtitles_kh.srt")
        if os.path.exists(file_path):
            return FileResponse(file_path, media_type="text/plain")
            
    raise HTTPException(status_code=404, detail=f"Subtitles format {format} not found")

@app.get("/api/downloads/{project_id}/thumbnail/{filename}")
async def download_thumbnail(project_id: str, filename: str, db: Session = Depends(get_db)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project_dir = os.path.join(DATA_DIR, project_id)
    file_path = os.path.join(project_dir, "thumbnails", filename)
    
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="image/jpeg")
        
    raise HTTPException(status_code=404, detail=f"Thumbnail {filename} not found")

@app.post("/api/projects/{project_id}/cancel")
async def cancel_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project.status = "cancelled"
    db.commit()
    return {"message": "Project cancellation requested", "project_id": project_id}

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    db.delete(project)
    db.commit()
    
    project_dir = os.path.join(DATA_DIR, project_id)
    if os.path.exists(project_dir):
        shutil.rmtree(project_dir, ignore_errors=True)
        
    return {"message": "Project deleted successfully", "project_id": project_id}

if frontend_dir:
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="static")