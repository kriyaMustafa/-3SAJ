import os
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
                except Exception as e:
                    print(f"[WebSocket] Broadcast error: {e}")

ws_manager = WebSocketManager()

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
    generate_shorts = payload.get("generate_shorts", False)

    if not input_type or not input_source:
        raise HTTPException(status_code=400, detail="Missing required parameters")

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

    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "input_type": project.input_type,
            "input_source": project.input_source,
            "source_language": project.source_language,
            "target_language": project.target_language,
            "genre_mode": project.genre_mode,
            "generate_shorts": project.generate_shorts,
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
    
    # Delete folder from disk
    project_dir = os.path.join(DATA_DIR, project_id)
    if os.path.exists(project_dir):
        try:
            shutil.rmtree(project_dir)
        except Exception as e:
            print(f"[Backend] Error deleting project files: {e}")
            
    # Delete from database (cascades automatically to segments, chunks, thumbnails)
    db.delete(project)
    db.commit()
    return {"message": "Project deleted successfully", "project_id": project_id}


@app.get("/api/downloads/{project_id}/video/{format_type}")
async def download_video(project_id: str, format_type: str, db: Session = Depends(get_db)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    file_path = None
    if format_type == "16_9":
        file_path = project.output_video_16_9
    elif format_type == "9_16":
        file_path = project.output_video_9_16
    elif format_type == "original":
        file_path = project.video_path

    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=400, detail="Requested file format not found or not rendered yet")

    return FileResponse(file_path, filename=os.path.basename(file_path))


def format_srt_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


@app.get("/api/downloads/{project_id}/subtitles/srt")
async def download_srt(project_id: str, db: Session = Depends(get_db)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    segments = db.query(models.Segment).filter(
        models.Segment.project_id == project_id
    ).order_by(models.Segment.start_time).all()

    srt_content = ""
    for idx, seg in enumerate(segments, 1):
        start_str = format_srt_time(seg.start_time)
        end_str = format_srt_time(seg.end_time)
        text = seg.translated_text or ""
        srt_content += f"{idx}\n{start_str} --> {end_str}\n{text}\n\n"

    from fastapi.responses import Response
    return Response(
        content=srt_content,
        media_type="application/x-subrip",
        headers={"Content-Disposition": f"attachment; filename=subtitles_{project_id[:8]}.srt"}
    )


@app.get("/api/downloads/{project_id}/audio/mp3")
async def download_audio_mp3(project_id: str, db: Session = Depends(get_db)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    video_path = project.output_video_16_9
    if not video_path or not os.path.exists(video_path):
        raise HTTPException(status_code=400, detail="Dubbed video not found or not rendered yet")

    # Extract audio to MP3 using ffmpeg
    mp3_path = os.path.join(os.path.dirname(video_path), f"dubbed_{project_id[:8]}.mp3")
    if not os.path.exists(mp3_path):
        try:
            import subprocess
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            subprocess.run([
                ffmpeg_exe, "-y", "-i", video_path, "-vn", "-acodec", "libmp3lame", "-aq", "2", mp3_path
            ], check=True, capture_output=True)
        except Exception as e:
            print(f"[Backend] Error extracting MP3 audio: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to extract audio track: {e}")

    return FileResponse(mp3_path, media_type="audio/mp3", filename=f"dubbed_audio_{project_id[:8]}.mp3")

@app.get("/api/downloads/{project_id}/thumbnail/{filename}")
async def download_thumbnail(project_id: str, filename: str):
    project_dir = os.path.join(DATA_DIR, project_id)
    file_path = os.path.join(project_dir, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    return FileResponse(file_path)

# WebSocket Endpoint
@app.websocket("/ws/progress/{project_id}")
async def websocket_progress(websocket: WebSocket, project_id: str):
    await ws_manager.connect(project_id, websocket)
    try:
        while True:
            try:
                db = SessionLocal()
                try:
                    project = db.query(models.Project).filter(models.Project.id == project_id).first()
                    if project:
                        chunks = db.query(models.VideoChunk).filter(models.VideoChunk.project_id == project_id).all()
                        total_chunks = len(chunks)
                        completed_chunks = sum(1 for c in chunks if c.status == "completed")
                        failed_chunks = sum(1 for c in chunks if c.status == "failed")

                        segments = db.query(models.Segment).filter(models.Segment.project_id == project_id).all()
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

                        status_payload = {
                            "project_id": project_id,
                            "status": project.status,
                            "progress": progress_percentage,
                            "chunks": {
                                "total": total_chunks,
                                "completed": completed_chunks,
                                "failed": failed_chunks
                            },
                            "segments": {
                                "total": total_segments,
                                "completed": completed_segments
                            }
                        }
                        await websocket.send_json(status_payload)
                except (WebSocketDisconnect, RuntimeError) as ws_err:
                    raise ws_err
                except Exception as e:
                    print(f"[WebSocket] Query error: {e}")
                finally:
                    db.close()

                await asyncio.sleep(1)
            except (WebSocketDisconnect, asyncio.CancelledError):
                print(f"[WebSocket] Progress session ended for project {project_id}")
                break
    except Exception as e:
        print(f"[WebSocket] Exception: {e}")
    finally:
        ws_manager.disconnect(project_id, websocket)
        if websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close()
            except Exception:
                pass


if frontend_dir:
    print(f"[Backend] Serving frontend static files from: {frontend_dir}")
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

