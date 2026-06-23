import os
import sys
import time
import math
import json
import uuid
import shutil
import gc
import traceback
import subprocess
from datetime import datetime, timedelta
from threading import Thread
import socket

from celery import Celery
from sqlalchemy.orm import Session

from database import SessionLocal, engine
import models

# Helper to check if Redis is running
def is_redis_running():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        if "@" in redis_url:
            host_port = redis_url.split("@")[1].split("/")[0]
        else:
            host_port = redis_url.split("//")[1].split("/")[0]
        if ":" in host_port:
            host, port = host_port.split(":")
            port = int(port)
        else:
            host, port = host_port, 6379
        s = socket.create_connection((host, port), timeout=0.2)
        s.close()
        return True
    except:
        return False

def is_project_cancelled(project_id: str) -> bool:
    db = SessionLocal()
    try:
        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if project and project.status == "cancelled":
            return True
        return False
    except Exception as e:
        print(f"Error checking project cancellation: {e}")
        return False
    finally:
        db.close()

# Helper to dispatch task either via Celery or local background threads
def dispatch_task(task, *args, background_tasks=None, **kwargs):
    if is_redis_running():
        print(f"[Celery] Dispatching {task.__name__} via Celery...")
        task.delay(*args, **kwargs)
    else:
        print(f"[Thread Fallback] Redis offline. Dispatching {task.__name__} in background thread...")
        if background_tasks:
            background_tasks.add_task(task, *args, **kwargs)
        else:
            t = Thread(target=task, args=args, kwargs=kwargs)
            t.start()


# Initialize SQLAlchemy tables
models.Base.metadata.create_all(bind=engine)

# Celery Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
app = Celery("translation_tasks", broker=REDIS_URL, backend=REDIS_URL)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "tasks.task_ingest_and_scraping": {"queue": "ingest"},
        "tasks.task_demucs_separation": {"queue": "gpu"},
        "tasks.task_whisper_transcription": {"queue": "gpu"},
        "tasks.task_translate_segments": {"queue": "translation"},
        "tasks.task_synthesize_tts_segment": {"queue": "gpu"},
        "tasks.task_re_render_segment": {"queue": "gpu"},
        "tasks.task_composite_and_export": {"queue": "export"},
        "tasks.task_cleanup_old_projects": {"queue": "export"},
    }
)

DATA_DIR = "/app/data" if os.path.exists("/app") else "./data"
os.makedirs(DATA_DIR, exist_ok=True)

def run_command_with_timeout(cmd, timeout=300, capture_output=False, project_id=None, db=None, **kwargs):
    """
    Runs a command with a strict timeout, handles stdout/stderr to avoid deadlocks,
    and terminates the process tree if a timeout occurs.
    """
    if not capture_output and "stdout" not in kwargs:
        kwargs["stdout"] = subprocess.DEVNULL
    if not capture_output and "stderr" not in kwargs:
        kwargs["stderr"] = subprocess.DEVNULL
    
    if capture_output:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
        
    proc = None
    try:
        proc = subprocess.Popen(cmd, **kwargs)
        stdout, stderr = proc.communicate(timeout=timeout)
        
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(
                returncode=proc.returncode,
                cmd=cmd,
                output=stdout,
                stderr=stderr
            )
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr
        )
    except subprocess.TimeoutExpired as e:
        print(f"[run_command_with_timeout] Pipeline stage timed out during execution. Command: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
        if proc:
            try:
                if os.name == 'nt':
                    # Windows process tree kill
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    # Unix process group / process kill
                    proc.kill()
            except Exception as kill_err:
                print(f"Error terminating subprocess {proc.pid}: {kill_err}")
        
        if project_id and db:
            try:
                project = db.query(models.Project).filter(models.Project.id == project_id).first()
                if project:
                    project.status = "failed"
                    db.commit()
            except Exception as db_err:
                print(f"Failed to update status to failed in database: {db_err}")
                
        raise e

# VRAM Model cycling manager
class GPUModelManager:
    _current_model_name = None
    _loaded_model = None

    @classmethod
    def unload_current(cls):
        if cls._loaded_model is not None:
            print(f"[VRAM] Unloading model: {cls._current_model_name}")
            del cls._loaded_model
            cls._loaded_model = None
            cls._current_model_name = None
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

    @classmethod
    def load_model(cls, model_name: str, load_fn):
        if cls._current_model_name == model_name:
            return cls._loaded_model
        
        cls.unload_current()
        print(f"[VRAM] Loading model: {model_name}")
        cls._loaded_model = load_fn()
        cls._current_model_name = model_name
        return cls._loaded_model

def get_db():
    db = SessionLocal()
    try:
        return db
    except Exception as e:
        print(f"Error opening database: {e}")
        return None

# =====================================================================
# QUEUE 0: Ingestion & Smart Scraping
# =====================================================================

@app.task(name="tasks.task_ingest_and_scraping")
def task_ingest_and_scraping(project_id: str):
    db = get_db()
    if not db:
        return {"status": "failed", "error": "Database unavailable"}
    
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        return {"status": "failed", "error": f"Project {project_id} not found"}

    try:
        project.status = "ingesting"
        db.commit()

        project_dir = os.path.join(DATA_DIR, project_id)
        os.makedirs(project_dir, exist_ok=True)

        video_path = None
        audio_path = None

        if project.input_type == "url":
            if is_project_cancelled(project_id):
                print(f"[Queue 0] Project {project_id} cancelled. Aborting URL ingestion.")
                return

            print(f"[Queue 0] Processing remote URL: {project.input_source}")
            audio_path = os.path.join(project_dir, "source_audio.wav")
            video_path = os.path.join(project_dir, "source_video.mp4")

            # 1. Download audio stream only using yt-dlp first
            audio_cmd = [
                "yt-dlp",
                "-f", "ba",
                "-x",
                "--audio-format", "wav",
                "-o", os.path.join(project_dir, "source_audio.%(ext)s"),
                project.input_source
            ]
            print(f"[Queue 0] Fetching audio-only stream with Chrome impersonation: {' '.join(audio_cmd)}")
            try:
                run_command_with_timeout(audio_cmd, timeout=300, capture_output=True, project_id=project_id, db=db)
            except subprocess.TimeoutExpired as timeout_err:
                print("[Queue 0] Pipeline stage timed out during execution. yt-dlp audio download timed out.")
                project.status = "failed"
                db.commit()
                raise Exception("Pipeline stage timed out during execution.") from timeout_err
            except subprocess.CalledProcessError as yt_err:
                stderr_str = yt_err.stderr.decode("utf-8", errors="replace") if yt_err.stderr else str(yt_err)
                print(f"[Queue 0] yt-dlp download failed: {stderr_str}")
                project.status = "failed"
                db.commit()
                raise Exception(f"Video download failed via yt-dlp: {stderr_str}") from yt_err
            except Exception as yt_err:
                print(f"[Queue 0] yt-dlp download failed with unexpected error: {yt_err}")
                project.status = "failed"
                db.commit()
                raise Exception(f"Video download failed via yt-dlp: {yt_err}") from yt_err
            
            # Match standard output filename
            for f in os.listdir(project_dir):
                if f.startswith("source_audio") and f.endswith(".wav"):
                    audio_path = os.path.join(project_dir, f)
                    break

            # 2. Trigger Queue 1 (Source Separation) immediately while video downloads in a thread
            project.vocals_path = os.path.join(project_dir, "vocals.wav")
            project.bgm_path = os.path.join(project_dir, "bgm.wav")
            db.commit()

            print(f"[Queue 0] Audio fetched. Queuing demucs task...")
            demucs_task = dispatch_task(task_demucs_separation, project_id, audio_path)

            # 3. Fetch video stream concurrently
            video_download_failed = [False]  # Use list so closure can mutate it
            video_download_error = [None]

            def download_video_stream():
                if is_project_cancelled(project_id):
                    print(f"[Queue 0] Video download thread aborted due to project cancellation.")
                    return
                thread_db = get_db()
                try:
                    video_cmd = [
                        "yt-dlp",
                        "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]",
                        "-o", video_path,
                        project.input_source
                    ]
                    print(f"[Queue 0] Downloader thread pulling full video stream: {' '.join(video_cmd)}")
                    run_command_with_timeout(video_cmd, timeout=300, capture_output=True, project_id=project_id, db=thread_db)
                    print(f"[Queue 0] Full video download completed.")
                except subprocess.TimeoutExpired as timeout_err:
                    print("[Queue 0] Pipeline stage timed out during execution. yt-dlp video download timed out.")
                    video_download_failed[0] = True
                    video_download_error[0] = "Video download timed out."
                except subprocess.CalledProcessError as yt_err:
                    stderr_str = yt_err.stderr.decode("utf-8", errors="replace") if yt_err.stderr else str(yt_err)
                    print(f"[Queue 0] Video download thread failed (CalledProcessError): {stderr_str}")
                    video_download_failed[0] = True
                    video_download_error[0] = stderr_str
                except Exception as e:
                    print(f"[Queue 0] Video download thread failed with unexpected error: {e}")
                    video_download_failed[0] = True
                    video_download_error[0] = str(e)
                finally:
                    if thread_db:
                        thread_db.close()

            dl_thread = Thread(target=download_video_stream)
            dl_thread.start()
            dl_thread.join()  # Wait for completion

            # Only fail if the VIDEO download itself failed (not demucs which runs concurrently)
            if video_download_failed[0]:
                project.status = "failed"
                db.commit()
                raise Exception(f"Video stream download failed: {video_download_error[0]}")

        else:
            # Local file processing
            print(f"[Queue 0] Processing local file path: {project.input_source}")
            if not os.path.exists(project.input_source):
                raise FileNotFoundError(f"Local file not found: {project.input_source}")
            
            # Copy local video to project dir
            video_path = os.path.join(project_dir, "source_video.mp4")
            shutil.copy(project.input_source, video_path)

            # Extract audio from local video
            audio_path = os.path.join(project_dir, "source_audio.wav")
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                audio_path
            ]
            try:
                run_command_with_timeout(ffmpeg_cmd, timeout=300, project_id=project_id, db=db)
            except subprocess.TimeoutExpired as timeout_err:
                print("[Queue 0] Pipeline stage timed out during execution. ffmpeg audio extraction timed out.")
                project.status = "failed"
                db.commit()
                raise Exception("Pipeline stage timed out during execution.") from timeout_err

            # Trigger Queue 1
            dispatch_task(task_demucs_separation, project_id, audio_path)

        # Slice video & audio into 60-second chunks for parallel processing
        # We query the length of the video using ffprobe
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ]
        try:
            res = run_command_with_timeout(probe_cmd, timeout=300, capture_output=True, project_id=project_id, db=db)
            duration_str = res.stdout.decode("utf-8").strip()
        except subprocess.TimeoutExpired as timeout_err:
            print("[Queue 0] Pipeline stage timed out during execution. ffprobe duration query timed out.")
            project.status = "failed"
            db.commit()
            raise Exception("Pipeline stage timed out during execution.") from timeout_err
        
        duration = float(duration_str)
        num_chunks = math.ceil(duration / 60.0)

        print(f"[Queue 0] Duration: {duration}s, Slicing into {num_chunks} chunks.")
        project.video_path = video_path
        db.commit()

        if is_project_cancelled(project_id):
            print(f"[Queue 0] Project {project_id} cancelled. Aborting slicing.")
            return

        for i in range(num_chunks):
            if is_project_cancelled(project_id):
                print(f"[Queue 0] Project {project_id} cancelled. Aborting slicing loop.")
                return
            start_s = i * 60
            chunk_video_path = os.path.join(project_dir, f"chunk_{i}.mp4")
            chunk_audio_path = os.path.join(project_dir, f"chunk_{i}.wav")

            # Slice audio
            slice_audio_cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_s),
                "-t", "60",
                "-i", audio_path,
                "-acodec", "pcm_s16le",
                chunk_audio_path
            ]
            try:
                run_command_with_timeout(slice_audio_cmd, timeout=300, project_id=project_id, db=db)
            except subprocess.TimeoutExpired as timeout_err:
                print("[Queue 0] Pipeline stage timed out during execution. ffmpeg audio slicing timed out.")
                project.status = "failed"
                db.commit()
                raise Exception("Pipeline stage timed out during execution.") from timeout_err

            # Slice video
            slice_video_cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_s),
                "-t", "60",
                "-i", video_path,
                "-c", "copy",
                chunk_video_path
            ]
            try:
                run_command_with_timeout(slice_video_cmd, timeout=300, project_id=project_id, db=db)
            except subprocess.TimeoutExpired as timeout_err:
                print("[Queue 0] Pipeline stage timed out during execution. ffmpeg video slicing timed out.")
                project.status = "failed"
                db.commit()
                raise Exception("Pipeline stage timed out during execution.") from timeout_err

            chunk_record = models.VideoChunk(
                project_id=project_id,
                chunk_index=i,
                chunk_video_path=chunk_video_path,
                chunk_audio_path=chunk_audio_path,
                status="pending"
            )
            db.add(chunk_record)

        db.commit()
        return {"status": "success", "duration": duration, "chunks": num_chunks}
    
    except Exception as e:
        tb = traceback.format_exc()
        project.status = "failed"
        db.commit()
        print(f"[Queue 0] Failed during ingestion. Traceback:\n{tb}")
        return {"status": "failed", "error": str(e), "traceback": tb}
    finally:
        db.close()

# =====================================================================
# QUEUE 1: Source Separation (GPU Worker - Cycle 1)
# =====================================================================

@app.task(name="tasks.task_demucs_separation")
def task_demucs_separation(project_id: str, audio_path: str):
    db = get_db()
    if not db:
        return {"status": "failed", "error": "Database unavailable"}

    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        db.close()
        return {"status": "failed", "error": "Project not found"}

    try:
        project.status = "stemming"
        db.commit()

        if is_project_cancelled(project_id):
            print(f"[Queue 1] Project {project_id} cancelled. Aborting Demucs separation.")
            return

        project_dir = os.path.join(DATA_DIR, project_id)
        
        # We run Demucs. To prevent concurrent heavy model VRAM loading, we call
        # demucs via subprocess so that the memory is released entirely on exit.
        demucs_out_dir = os.path.join(project_dir, "demucs_out")
        os.makedirs(demucs_out_dir, exist_ok=True)

        # Use absolute paths — demucs CLI on Windows fails on relative paths containing spaces.
        # Run via explicit venv Python with PYTHONNOUSERSITE=1 to avoid picking up incompatible
        # packages from system Python 3.14 user site-packages (torchcodec DLL conflict).
        abs_audio_path = os.path.abspath(audio_path)
        abs_demucs_out_dir = os.path.abspath(demucs_out_dir)
        demucs_device = os.getenv("DEMUCS_DEVICE", "cpu")
        venv_python = os.path.abspath(
            os.path.join(os.path.dirname(sys.executable), "python.exe")
        ) if os.name == "nt" else sys.executable
        print(f"[Queue 1] Starting Demucs separation on: {abs_audio_path} (device={demucs_device})")
        print(f"[Queue 1] Using Python: {venv_python}")
        demucs_cmd = [
            venv_python, "-m", "demucs",
            "--two-stems", "vocals",
            "--device", demucs_device,
            "-o", abs_demucs_out_dir,
            abs_audio_path
        ]
        # Build a clean environment: inherit current env but block user site-packages
        demucs_env = os.environ.copy()
        demucs_env["PYTHONNOUSERSITE"] = "1"
        demucs_env.pop("PYTHONPATH", None)  # clear any conflicting PYTHONPATH
        # Run Demucs — on Windows demucs writes progress to stderr which may cause
        # non-zero exit codes. We tolerate the exit code and check output files instead.
        try:
            demucs_result = subprocess.run(
                demucs_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,
                env=demucs_env
            )
            stdout_txt = demucs_result.stdout.decode("utf-8", errors="replace")
            stderr_txt = demucs_result.stderr.decode("utf-8", errors="replace")
            print(f"[Queue 1] Demucs exit code: {demucs_result.returncode}")
            if stderr_txt.strip():
                # Print full stderr so we can see any errors after the progress bars
                print(f"[Queue 1] Demucs stderr:\n{stderr_txt}")
        except subprocess.TimeoutExpired as timeout_err:
            print("[Queue 1] Pipeline stage timed out during execution. Demucs separation timed out.")
            project.status = "failed"
            db.commit()
            raise Exception("Pipeline stage timed out during execution.") from timeout_err

        # Retrieve isolated vocals and background music.
        # Demucs may flush output files slightly after subprocess exits (especially under
        # I/O load from concurrent video download/chunking), so poll up to 30 seconds.
        vocal_src = None
        bgm_src = None
        for _attempt in range(30):
            for root, dirs, files in os.walk(demucs_out_dir):
                for file in files:
                    if file == "vocals.wav":
                        fpath = os.path.join(root, file)
                        if os.path.getsize(fpath) > 0:
                            vocal_src = fpath
                    elif file in ("no_vocals.wav", "accompaniment.wav", "background.wav"):
                        fpath = os.path.join(root, file)
                        if os.path.getsize(fpath) > 0:
                            bgm_src = fpath
            if vocal_src and bgm_src:
                print(f"[Queue 1] Demucs output files ready after {_attempt}s.")
                break
            print(f"[Queue 1] Waiting for demucs output files... attempt {_attempt+1}/30")
            time.sleep(1)

        if not vocal_src or not bgm_src:
            raise FileNotFoundError("Demucs failed to produce vocals or background audio files.")

        vocals_dest = os.path.join(project_dir, "vocals.wav")
        bgm_dest = os.path.join(project_dir, "bgm.wav")

        shutil.move(vocal_src, vocals_dest)
        shutil.move(bgm_src, bgm_dest)

        project.vocals_path = vocals_dest
        project.bgm_path = bgm_dest
        db.commit()

        print(f"[Queue 1] Source separation completed successfully.")
        
        # Trigger Queue 2 (Transcription)
        dispatch_task(task_whisper_transcription, project_id, vocals_dest)
        return {"status": "success", "vocals": vocals_dest, "bgm": bgm_dest}

    except Exception as e:
        tb = traceback.format_exc()
        project.status = "failed"
        db.commit()
        print(f"[Queue 1] Demucs separation failed. Traceback:\n{tb}")
        return {"status": "failed", "error": str(e), "traceback": tb}
    finally:
        db.close()

# =====================================================================
# QUEUE 2: Transcription & Forced Alignment (GPU Worker - Cycle 2)
# =====================================================================

@app.task(name="tasks.task_whisper_transcription")
def task_whisper_transcription(project_id: str, vocals_path: str):
    db = get_db()
    if not db:
        return {"status": "failed", "error": "Database unavailable"}

    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        db.close()
        return {"status": "failed", "error": "Project not found"}

    try:
        project.status = "transcribing"
        db.commit()

        if is_project_cancelled(project_id):
            print(f"[Queue 2] Project {project_id} cancelled. Aborting Whisper transcription.")
            return

        # VRAM Cycle: Unload any loaded models first
        GPUModelManager.unload_current()

        # Load whisper model dynamically inside the task for memory management
        def load_whisper():
            from faster_whisper import WhisperModel
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            print(f"[Queue 2] Loading Whisper model on: {device}")
            return WhisperModel("small", device=device, compute_type="float16" if device == "cuda" else "int8")

        model = GPUModelManager.load_model("whisper", load_whisper)

        # ── Path normalisation fix for Windows paths with spaces ──
        # faster_whisper uses PyAV internally which fails on relative or
        # non-normalised Windows paths. Resolve to absolute path first.
        vocals_path_abs = os.path.abspath(vocals_path).replace("\\", "/")
        if not os.path.exists(vocals_path_abs):
            raise FileNotFoundError(f"[Queue 2] vocals file not found: {vocals_path_abs}")
        print(f"[Queue 2] Running Whisper transcription on: {vocals_path_abs}")
        segments, info = model.transcribe(vocals_path_abs, beam_size=5, language=project.source_language)
        
        segment_list = list(segments)
        print(f"[Queue 2] Transcribed {len(segment_list)} segments. Aligning times...")

        # Process each segment and write to Database
        for idx, seg in enumerate(segment_list):
            chunk_idx = int(seg.start // 60)
            
            db_segment = models.Segment(
                project_id=project_id,
                chunk_index=chunk_idx,
                segment_index=idx,
                speaker_id=f"Speaker {getattr(seg, 'speaker', 0)}",
                start_time=seg.start,
                end_time=seg.end,
                original_text=seg.text.strip(),
                status="pending"
            )
            db.add(db_segment)

        db.commit()
        print(f"[Queue 2] Transcription completed.")

        # Unload Whisper model from VRAM immediately to clear space
        GPUModelManager.unload_current()

        # Trigger Queue 3 (Translation)
        dispatch_task(task_translate_segments, project_id)
        return {"status": "success", "segments_count": len(segment_list)}

    except Exception as e:
        tb = traceback.format_exc()
        project.status = "failed"
        db.commit()
        print(f"[Queue 2] Whisper transcription failed. Traceback:\n{tb}")
        return {"status": "failed", "error": str(e), "traceback": tb}
    finally:
        db.close()

# =====================================================================
# QUEUE 3: Conditional Language Routing & Genre-Aware Translation
# =====================================================================

@app.task(name="tasks.task_translate_segments")
def task_translate_segments(project_id: str):
    db = get_db()
    if not db:
        return {"status": "failed", "error": "Database not found"}

    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        db.close()
        return {"status": "failed", "error": "Project not found"}

    try:
        project.status = "translating"
        db.commit()

        if is_project_cancelled(project_id):
            print(f"[Queue 3] Project {project_id} cancelled. Aborting translation.")
            return

        segments = db.query(models.Segment).filter(models.Segment.project_id == project_id).order_by(models.Segment.segment_index).all()
        
        # Branch A: source_language matches target_language -> Bypass translation
        if project.source_language == project.target_language:
            print(f"[Queue 3] Source and Target languages are identical ({project.source_language}). Bypassing translation.")
            for seg in segments:
                seg.translated_text = seg.original_text
                seg.status = "translated"
            db.commit()
            
            for seg in segments:
                if is_project_cancelled(project_id):
                    return
                dispatch_task(task_synthesize_tts_segment, project_id, seg.id)
            return {"status": "success", "detail": "Bypassed translation"}

        # Branch B: Translation via Gemini API
        print(f"[Queue 3] Starting Translation with rolling context windows via Gemini...")
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("[Queue 3] WARNING: GEMINI_API_KEY environment variable is empty. Falling back to offline translation.")

        gemini_disabled = False
        for i, current_seg in enumerate(segments):
            if is_project_cancelled(project_id):
                print(f"[Queue 3] Project {project_id} cancelled. Aborting translation loop.")
                return

            # 1. Validate Input Data
            if not current_seg.original_text or not current_seg.original_text.strip():
                print(f"[Queue 3] Segment {current_seg.id} original text is empty or invalid. Skipping Gemini call.")
                current_seg.translated_text = ""
                current_seg.status = "translated"
                db.commit()
                dispatch_task(task_synthesize_tts_segment, project_id, current_seg.id)
                continue

            try:
                context_texts = []
                for prev_seg in segments[:i]:
                    if current_seg.start_time - prev_seg.end_time <= 120:
                        context_texts.append(f"{prev_seg.original_text} -> {prev_seg.translated_text or ''}")

                context_str = "\n".join(context_texts[-5:])

                # Verify the language variable, default strictly to 'Khmer' if missing/empty
                target_lang = project.target_language.strip() if project.target_language else ""
                if not target_lang:
                    target_lang = "km"

                genre_instructions = ""
                if project.genre_mode == "anime_recap":
                    genre_instructions = (
                        f"Target language is '{target_lang}'. Anime recaps are fast-paced. "
                        "Summarize the translation so the spoken words fit the tight original time window. "
                        "Prioritize punchy, high-energy summaries over literal translation."
                    )
                else:  # drama_recap
                    genre_instructions = (
                        f"Target language is '{target_lang}'. Focus on emotional accuracy "
                        "and dramatic storytelling, maintaining natural conversational flow within the timestamps."
                    )

                # Map target language key to human readable names for Gemini
                lang_mapping = {
                    "km": "Khmer", "en": "English", "zh": "Chinese",
                    "ja": "Japanese", "ko": "Korean", "es": "Spanish"
                }
                target_lang_name = lang_mapping.get(target_lang.lower(), target_lang)

                # 2. Highly Strict, Zero-Shot System Instruction
                system_instruction = (
                    f"You are an elite localization translator for drama, anime, and manga content. Your job is to translate the provided English transcript into {target_lang_name}.\n"
                    "CRITICAL INSTRUCTIONS:\n"
                    f"1. You must output ONLY the {target_lang_name} translated text.\n"
                    "2. Do NOT include explanations, notes, intros, or markdown formatting.\n"
                    "3. Do NOT include or repeat the original English text.\n"
                    "4. Do NOT wrap your output in quotation marks.\n"
                    "5. Translate completely—do not truncate, leave empty, or cut off sentences."
                )

                prompt = (
                    f"{system_instruction}\n\n"
                    f"Genre context and constraints:\n{genre_instructions}\n\n"
                    f"Context (Previous translations for reference):\n{context_str}\n\n"
                    f"Translate the following text directly. Output ONLY the translated text, no quotes, no explanations, no comments:\n"
                    f"\"{current_seg.original_text}\""
                )

                translated_text = ""
                if api_key and not gemini_disabled:
                    # 3. Gemini call with exponential backoff retry for 429 rate limiting
                    max_retries = 5
                    base_delay = 5.0
                    for attempt in range(max_retries):
                        try:
                            from google import genai
                            client = genai.Client(api_key=api_key)
                            response = client.models.generate_content(
                                model='gemini-2.5-flash',
                                contents=prompt,
                            )
                            raw_text = response.text
                            if isinstance(raw_text, str):
                                # 4. Standardize and Clean the Output String
                                translated_text = raw_text.strip(" \"'\n\r")
                            else:
                                translated_text = "[TRANSLATION_FAILED: Invalid API Response]"
                            break  # Success — exit retry loop
                        except Exception as api_err:
                            err_str = str(api_err)
                            # Detect permanent quota limit first
                            if "quota" in err_str.lower() or ("limit" in err_str.lower() and "exceeded" in err_str.lower()):
                                print(f"[Queue 3] Permanent Gemini quota limit exceeded: {err_str}. Disabling Gemini for this run.")
                                gemini_disabled = True
                                translated_text = "[TRANSLATION_FAILED: Quota Exceeded]"
                                break
                            # Detect 429 rate limit and parse retryDelay if available
                            elif "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "503" in err_str or "UNAVAILABLE" in err_str:
                                retry_delay = base_delay * (2 ** attempt)  # Exponential backoff
                                # Try to extract server-suggested retryDelay
                                try:
                                    import re as _re
                                    delay_match = _re.search(r'retryDelay.*?(\d+)s', err_str)
                                    if delay_match:
                                        retry_delay = min(float(delay_match.group(1)) + 2.0, 120.0)
                                except Exception:
                                    pass
                                print(f"[Queue 3] Gemini 429 rate limit on segment {current_seg.id} (attempt {attempt+1}/{max_retries}). Backing off {retry_delay:.0f}s...")
                                if attempt < max_retries - 1:
                                    time.sleep(retry_delay)
                                else:
                                    print(f"[Queue 3] Gemini rate limit: all {max_retries} retries exhausted for segment {current_seg.id}. Falling back to deep_translator.")
                                    translated_text = "[TRANSLATION_FAILED: Rate Limited]"
                            else:
                                import logging
                                logging.error(f"Gemini Translation API failed for segment {current_seg.id}: {api_err}")
                                print(f"[Queue 3] Gemini API error (non-rate-limit): {api_err}")
                                translated_text = "[TRANSLATION_FAILED: API Error]"
                                break  # Non-retriable error, exit immediately

                    # Fallback: if Gemini produced a failure placeholder, try deep_translator
                    if not translated_text or translated_text.startswith("[TRANSLATION_FAILED"):
                        try:
                            from deep_translator import GoogleTranslator
                            dt_result = GoogleTranslator(
                                source=project.source_language or 'auto',
                                target=project.target_language or 'km'
                            ).translate(current_seg.original_text)
                            if dt_result and dt_result.strip():
                                translated_text = dt_result.strip()
                                print(f"[Queue 3] deep_translator fallback OK for segment {current_seg.id}: {translated_text[:60]}")
                        except Exception as dt_err:
                            print(f"[Queue 3] deep_translator fallback also failed: {dt_err}")
                else:
                    print(f"[Queue 3] Gemini API key is missing. Trying deep_translator fallback.")
                    try:
                        from deep_translator import GoogleTranslator
                        dt_result = GoogleTranslator(
                            source=project.source_language or 'auto',
                            target=project.target_language or 'km'
                        ).translate(current_seg.original_text)
                        if dt_result and dt_result.strip():
                            translated_text = dt_result.strip()
                        else:
                            translated_text = "[TRANSLATION_FAILED: API Key Missing]"
                    except Exception as dt_err:
                        print(f"[Queue 3] deep_translator also failed: {dt_err}")
                        translated_text = "[TRANSLATION_FAILED: API Key Missing]"

                current_seg.translated_text = translated_text
                current_seg.status = "translated"
                db.commit()

                # Only dispatch TTS if we actually have real translated text
                has_real_text = (
                    translated_text
                    and translated_text.strip()
                    and not translated_text.startswith("[TRANSLATION_FAILED")
                )
                if has_real_text:
                    dispatch_task(task_synthesize_tts_segment, project_id, current_seg.id)
                else:
                    print(f"[Queue 3] Skipping TTS dispatch for segment {current_seg.id} — no valid translation available.")
                    current_seg.status = "failed"
                    current_seg.error_traceback = f"Translation produced empty/failed text: {translated_text}"
                    db.commit()

            except Exception as segment_err:
                tb_seg = traceback.format_exc()
                current_seg.status = "failed"
                current_seg.error_traceback = tb_seg
                current_seg.translated_text = "[TRANSLATION_FAILED: Segment Processing Error]"
                db.commit()
                import logging
                logging.error(f"Translation logic crashed for segment {current_seg.id}: {segment_err}")
                print(f"[Queue 3] Segment {current_seg.id} crashed during translation: {segment_err}")

        project.status = "synthesizing"
        db.commit()
        return {"status": "success", "processed_segments": len(segments)}

    except Exception as e:
        tb = traceback.format_exc()
        project.status = "failed"
        db.commit()
        print(f"[Queue 3] Translation pipeline crashed: {tb}")
        return {"status": "failed", "error": str(e), "traceback": tb}
    finally:
        db.close()

# =====================================================================
# QUEUE 4: State-Driven Voice Design & Anti-Distortion Time-Stretching
# =====================================================================

@app.task(name="tasks.task_synthesize_tts_segment")
def task_synthesize_tts_segment(project_id: str, segment_id: int, force_no_shorten: bool = False):
    db = get_db()
    if not db:
        return {"status": "failed", "error": "Database connection unavailable"}

    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    segment = db.query(models.Segment).filter(models.Segment.id == segment_id).first()

    if not project or not segment:
        db.close()
        return {"status": "failed", "error": "Project or Segment not found"}

    try:
        if is_project_cancelled(project_id):
            print(f"[Queue 4] Project {project_id} cancelled. Aborting synthesis.")
            return

        project_dir = os.path.join(DATA_DIR, project_id)
        output_wav = os.path.join(project_dir, f"segment_{segment.segment_index}_tts.wav")
        final_wav  = os.path.join(project_dir, f"segment_{segment.segment_index}_final.wav")

        def load_tts_model():
            print("[Queue 4] Loading VoxCPM2 Voice Synthesis engine.")
            return "TTS_VOXCPM2_ENGINE"

        # VRAM Cycle load
        GPUModelManager.load_model("tts", load_tts_model)

        # Bug #3 Guard: Skip synthesis entirely if translated_text is empty or a failure placeholder
        import re
        raw_translated = (segment.translated_text or "").strip()
        is_failed_placeholder = raw_translated.startswith("[TRANSLATION_FAILED") or not raw_translated
        if is_failed_placeholder:
            print(f"[Queue 4] Segment {segment.segment_index} has no valid translation ('{raw_translated[:60]}'). Skipping synthesis — writing silent fallback.")
            import wave
            with wave.open(final_wav, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b'\x00' * 16000)  # 0.5s silence
            segment.audio_path = final_wav
            segment.status = "synthesized"
            db.commit()
            # Check if all segments done
            all_segments = db.query(models.Segment).filter(models.Segment.project_id == project_id).all()
            if all(s.status == "synthesized" for s in all_segments):
                print("[Queue 4] All segments completed (some silent fallbacks). Triggering export...")
                dispatch_task(task_composite_and_export, project_id)
            return {"status": "skipped", "reason": "no_valid_translation", "audio_path": final_wav}

        # Determine TTS backend
        tts_backend = os.getenv("TTS_BACKEND", "edge-tts").strip().lower()
        tts_success = False

        # Clean text to synthesize (remove bracketed tags like [Khmer Dub] or unclosed [Khmer)
        synth_text = segment.translated_text
        if synth_text:
            synth_text = re.sub(r'\[.*?\]', '', synth_text)
            synth_text = re.sub(r'^\[[^\]]*$', '', synth_text)
            synth_text = synth_text.strip()
        if not synth_text:
            synth_text = " "

        if tts_backend == "voxcpm2":
            try:
                import sys
                sys.path.append(os.path.dirname(os.path.abspath(__file__)))
                import voxcpm2
                print(f"[Queue 4] Using VoxCPM2 for synthesis of segment {segment.segment_index}...")
                profile = "female"
                if segment.speaker_id and "male" in str(segment.speaker_id).lower():
                    profile = "male"
                elif segment.speaker_id and "kid" in str(segment.speaker_id).lower():
                    profile = "kid"

                voxcpm2.generate(
                    text=synth_text,
                    output_path=output_wav,
                    voice_profile=profile,
                    target_lang=project.target_language
                )
                tts_success = os.path.exists(output_wav)
            except Exception as vox_exc:
                print(f"[Queue 4] VoxCPM2 synthesis failed: {vox_exc}. Falling back to edge-tts.")
                tts_success = False

        if not tts_success:
            # Run Edge-TTS (either as fallback or primary)
            # Do NOT prepend voice_style parenthetical text for Edge-TTS as it reads it out loud!
            voice_gender_neural = "km-KH-PisethNeural"
            if project.genre_mode == "anime_recap":
                voice_gender_neural = "km-KH-PisethNeural"
            else:
                voice_gender_neural = "km-KH-SreymomNeural"

            print(f"[Queue 4] Synthesizing segment {segment.segment_index} via Edge-TTS (text={repr(synth_text)})...")
            edge_cmd = [
                "edge-tts",
                "--voice", voice_gender_neural,
                "--text", synth_text,
                "--write-media", output_wav
            ]
            res = subprocess.run(edge_cmd, capture_output=True)
            if res.returncode != 0:
                print(f"[Queue 4] Edge-TTS error: {res.stderr.decode()}. Writing fallback silent wave.")
                import wave
                with wave.open(output_wav, 'wb') as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(16000)
                    w.writeframes(b'\x00' * 32000)


        # Time stretching checks
        original_duration = segment.end_time - segment.start_time
        if original_duration <= 0:
            original_duration = 1.0

        # Wait a small delay to ensure filesystem has finished writing and closing the file
        time.sleep(0.1)

        # 1. File Integrity Check
        if not os.path.exists(output_wav) or os.path.getsize(output_wav) == 0:
            print(f"[Queue 4] WARNING: TTS file {output_wav} is missing or empty. Writing fallback silent wave.")
            import wave
            with wave.open(output_wav, 'wb') as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(b'\x00' * 32000)

        # 2. Probe Duration with Try/Except to catch invalid or corrupt files
        synth_duration = 1.0  # default fallback duration
        try:
            probe_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                output_wav
            ]
            synth_duration_str = subprocess.check_output(probe_cmd).decode("utf-8").strip()
            synth_duration = float(synth_duration_str)
        except (subprocess.CalledProcessError, ValueError, Exception) as probe_err:
            print(f"[Queue 4] ffprobe failed for {output_wav}: {probe_err}. Re-writing silent fallback wave and using 1.0s duration.")
            import wave
            with wave.open(output_wav, 'wb') as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(b'\x00' * 32000)
            synth_duration = 1.0

        speed_multiplier = synth_duration / original_duration
        print(f"[Queue 4] Segment {segment.segment_index}: Original={original_duration:.2f}s, Synth={synth_duration:.2f}s. Speed={speed_multiplier:.2f}x")

        # Determine if we should attempt to shorten the text.
        # We only shorten if the speed multiplier exceeds 1.5x AND the text is long enough to be shortened (>= 15 chars).
        # Otherwise, we just time-stretch it (capping speedup at 2.0x).
        should_shorten = (speed_multiplier > 1.5) and (len(segment.translated_text) >= 15) and not force_no_shorten

        if not should_shorten:
            # Stretch audio smoothly
            atempo_val = max(0.5, min(2.0, speed_multiplier))
            stretch_cmd = [
                "ffmpeg", "-y",
                "-i", output_wav,
                "-filter:a", f"atempo={atempo_val}",
                final_wav
            ]
            subprocess.run(stretch_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            segment.audio_path = final_wav
            segment.status = "synthesized"
            db.commit()
            print(f"[Queue 4] Segment {segment.segment_index} time-stretched successfully (atempo={atempo_val:.2f}).")

        else:
            # Speed Multiplier > 1.5x and text is long enough -> Shorten sentence via Gemini.
            print(f"[Queue 4] Multiplier ({speed_multiplier:.2f}x) too high. Shortening via API...")

            api_key = os.getenv("GEMINI_API_KEY")
            shortened_text = segment.translated_text

            if api_key:
                try:
                    from google import genai
                    client = genai.Client(api_key=api_key)
                    shorten_prompt = (
                        f"The following text is too long to fit in its visual scene window ({original_duration:.1f} seconds).\n"
                        f"Text: \"{segment.translated_text}\"\n"
                        f"Task: Rewrite it into a much shorter, concise Khmer translation (1 single short sentence) that can be spoken in under {original_duration:.1f} seconds, while keeping the main recap meaning. Output only the short Khmer sentence:"
                    )
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=shorten_prompt,
                    )
                    shortened_text = response.text.strip()
                    print(f"[Queue 4] Shortened translation received: {shortened_text}")
                except Exception as api_err:
                    print(f"[Queue 4] Failed to get shortened text: {api_err}. Falling back to offline half-text shortening.")
                    shortened_text = segment.translated_text[:len(segment.translated_text)//2]
            else:
                shortened_text = segment.translated_text[:len(segment.translated_text)//2]

            # If for some reason it didn't actually shorten the text, force a change to prevent infinite loop
            if shortened_text == segment.translated_text or len(shortened_text) >= len(segment.translated_text):
                shortened_text = segment.translated_text[:max(1, len(segment.translated_text)//2)]

            if os.path.exists(output_wav):
                os.remove(output_wav)

            segment.translated_text = shortened_text
            db.commit()
            
            dispatch_task(task_synthesize_tts_segment, project_id, segment_id, force_no_shorten=True)
            return {"status": "requeued", "reason": "duration_exceeded"}

        # Compile check
        all_segments = db.query(models.Segment).filter(models.Segment.project_id == project_id).all()
        all_completed = all(s.status == "synthesized" for s in all_segments)
        if all_completed:
            print("[Queue 4] All segments completed. Compiling final rendering...")
            dispatch_task(task_composite_and_export, project_id)

        return {"status": "success", "audio_path": final_wav}

    except Exception as e:
        tb = traceback.format_exc()
        segment.status = "failed"
        segment.error_traceback = tb
        db.commit()
        print(f"[Queue 4] TTS synthesis failed for segment {segment_id}: {tb}")
        return {"status": "failed", "error": str(e), "traceback": tb}
    finally:
        db.close()

@app.task(name="tasks.task_re_render_segment")
def task_re_render_segment(project_id: str, segment_id: int):
    return task_synthesize_tts_segment(project_id, segment_id)

# =====================================================================
# QUEUE 5: Composite Rendering, Automation Upgrades & Export (CPU)
# =====================================================================

@app.task(name="tasks.task_composite_and_export")
def task_composite_and_export(project_id: str):
    db = get_db()
    if not db:
        return {"status": "failed", "error": "Database not found"}

    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        db.close()
        return {"status": "failed", "error": "Project not found"}

    try:
        project.status = "exporting"
        db.commit()

        project_dir = os.path.join(DATA_DIR, project_id)
        segments = db.query(models.Segment).filter(models.Segment.project_id == project_id).order_by(models.Segment.segment_index).all()

        # 1. Subtitles (.ass format)
        ass_path = os.path.join(project_dir, "subtitles.ass")
        write_ass_subtitles(ass_path, segments)

        # 2. Vocal mix & ducking BGM
        mixed_audio_path = os.path.join(project_dir, "final_dubbed_audio.wav")
        vocals_mix_path = os.path.join(project_dir, "vocals_mix.wav")

        assemble_vocals_track(vocals_mix_path, segments)

        ducking_filter = (
            f"[1:a]asplit[v_duck][v_direct];"
            f"[0:a][v_duck]sidechaincompress=threshold=0.15:ratio=4:attack=50:release=300:makeup=1.0[bgm_ducked];"
            f"[bgm_ducked][v_direct]amix=inputs=2:duration=first:dropout_transition=2[a_mixed]"
        )
        duck_cmd = [
            "ffmpeg", "-y",
            "-i", project.bgm_path,
            "-i", vocals_mix_path,
            "-filter_complex", ducking_filter,
            "-map", "[a_mixed]",
            mixed_audio_path
        ]
        subprocess.run(duck_cmd, check=True)

        # Convert path to forward slashes and escape backslashes/colons for ffmpeg filters on Windows
        ffmpeg_ass_path = ass_path.replace("\\", "/")
        if ":" in ffmpeg_ass_path:
            ffmpeg_ass_path = ffmpeg_ass_path.replace(":", "\\:")

        # Check if CUDA is available for GPU accelerated encoding
        import torch
        if torch.cuda.is_available():
            print("[Queue 5] CUDA GPU detected. Using h264_nvenc for fast video encoding.")
            video_encoder = ["-c:v", "h264_nvenc", "-preset", "fast", "-rc", "vbr", "-cq", "22"]
            shorts_encoder = ["-c:v", "h264_nvenc", "-preset", "fast", "-rc", "vbr", "-cq", "20"]
        else:
            print("[Queue 5] CUDA GPU not available or not active. Falling back to libx264 CPU encoding.")
            video_encoder = ["-c:v", "libx264", "-preset", "fast", "-crf", "22"]
            shorts_encoder = ["-c:v", "libx264", "-crf", "20"]

        # 3. Output 16:9 MP4 Video
        output_16_9 = os.path.join(project_dir, "output_16_9.mp4")
        video_cmd = [
            "ffmpeg", "-y",
            "-i", project.video_path,
            "-i", mixed_audio_path,
            "-map", "0:v",
            "-map", "1:a",
            "-vf", f"ass={ffmpeg_ass_path}",
        ] + video_encoder + [
            "-c:a", "aac",
            "-b:a", "192k",
            output_16_9
        ]
        subprocess.run(video_cmd, check=True)

        project.output_video_16_9 = output_16_9
        db.commit()

        # 4. Exporter 9:16 Shorts
        if project.generate_shorts:
            output_9_16 = os.path.join(project_dir, "output_9_16.mp4")
            best_start, best_end = find_highest_density_window(segments, window_size=60)
            
            crop_cmd = [
                "ffmpeg", "-y",
                "-ss", str(best_start),
                "-t", "60",
                "-i", output_16_9,
                "-vf", "crop=ih*9/16:ih:(iw-ow)/2:0,scale=1080:1920",
            ] + shorts_encoder + [
                "-c:a", "copy",
                output_9_16
            ]
            subprocess.run(crop_cmd, check=True)
            project.output_video_9_16 = output_9_16
            db.commit()

        # 5. Engagement Thumbnails
        capture_and_score_thumbnails(project_id, project.video_path, db)

        # 6. Boilerplates upload
        trigger_mock_social_shares(project_id)

        project.status = "completed"
        db.commit()

        # Schedule 24h cleanup
        task_cleanup_old_projects.apply_async(args=[project_id], countdown=86400)

        return {"status": "success", "output_16_9": output_16_9}

    except Exception as e:
        tb = traceback.format_exc()
        project.status = "failed"
        db.commit()
        print(f"[Queue 5] Composite rendering failed: {tb}")
        return {"status": "failed", "error": str(e), "traceback": tb}
    finally:
        db.close()

# =====================================================================
# QUEUE 5 HELPERS
# =====================================================================

def write_ass_subtitles(filepath: str, segments: list):
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("[Script Info]\n")
        f.write("Title: Dubbed Khmer Subtitles\n")
        f.write("ScriptType: v4.00+\n")
        f.write("PlayResX: 1920\n")
        f.write("PlayResY: 1080\n\n")
        f.write("[V4+ Styles]\n")
        f.write("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n")
        f.write("Style: Default,Outfit,48,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,3,1,2,10,10,50,1\n\n")
        f.write("[Events]\n")
        f.write("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
        
        for s in segments:
            start_str = format_ass_time(s.start_time)
            end_str = format_ass_time(s.end_time)
            txt = s.translated_text or ""
            f.write(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{txt}\n")

def format_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs == 100:
        cs = 99
    return f"{h:01d}:{m:02d}:{s:02d}.{cs:02d}"

def assemble_vocals_track(filepath: str, segments: list):
    import wave
    import numpy as np
    import soundfile as sf

    if not segments:
        return

    max_end = max(s.end_time for s in segments)
    sr = 16000
    total_samples = int(max_end * sr) + sr
    vocal_data = np.zeros(total_samples, dtype=np.float32)

    for s in segments:
        if s.audio_path and os.path.exists(s.audio_path):
            try:
                data, sample_rate = sf.read(s.audio_path)
                if sample_rate != sr:
                    import librosa
                    data = librosa.resample(data, orig_sr=sample_rate, target_sr=sr)
                
                start_sample = int(s.start_time * sr)
                end_sample = start_sample + len(data)
                
                if end_sample <= len(vocal_data):
                    vocal_data[start_sample:end_sample] += data
                else:
                    overflow = len(vocal_data) - start_sample
                    vocal_data[start_sample:] += data[:overflow]
            except Exception as e:
                print(f"Error loading segment wave: {e}")

    sf.write(filepath, vocal_data, sr)

def find_highest_density_window(segments: list, window_size: float = 60.0) -> tuple:
    if not segments:
        return (0.0, window_size)
    
    max_end = max(s.end_time for s in segments)
    if max_end <= window_size:
        return (0.0, max_end)

    best_start = 0.0
    max_chars = 0
    step = 5.0
    current_start = 0.0
    while current_start + window_size <= max_end:
        current_end = current_start + window_size
        chars_in_window = 0
        for s in segments:
            if s.start_time >= current_start and s.end_time <= current_end:
                chars_in_window += len(s.original_text)

        if chars_in_window > max_chars:
            max_chars = chars_in_window
            best_start = current_start
        current_start += step

    return (best_start, best_start + window_size)

def capture_and_score_thumbnails(project_id: str, video_path: str, db: Session):
    project_dir = os.path.join(DATA_DIR, project_id)
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    try:
        duration_str = subprocess.check_output(probe_cmd).decode("utf-8").strip()
        duration = float(duration_str)
    except:
        duration = 180.0

    step = 30.0
    current_time = 30.0
    api_key = os.getenv("GEMINI_API_KEY")

    while current_time < duration - 10:
        thumb_name = f"thumbnail_{int(current_time)}.jpg"
        thumb_path = os.path.join(project_dir, thumb_name)

        shot_cmd = [
            "ffmpeg", "-y",
            "-ss", str(current_time),
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            thumb_path
        ]
        subprocess.run(shot_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if os.path.exists(thumb_path):
            score = 50.0
            if api_key:
                try:
                    from google import genai
                    from PIL import Image
                    client = genai.Client(api_key=api_key)
                    img = Image.open(thumb_path)
                    
                    score_prompt = (
                        "Evaluate this thumbnail image for a video recap catalog. "
                        "Rate its visual quality, emotional expression, and engagement level from 0 to 100. "
                        "Output ONLY a single floating-point number, e.g. 78.5"
                    )
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=[img, score_prompt],
                    )
                    score = float(response.text.strip())
                except Exception as api_err:
                    print(f"Gemini thumbnail score exception: {api_err}")

            thumbnail_record = models.Thumbnail(
                project_id=project_id,
                path=thumb_path,
                score=score,
                timestamp=current_time
            )
            db.add(thumbnail_record)
        current_time += step

    db.commit()

def trigger_mock_social_shares(project_id: str):
    print(f"[YouTube/TikTok] Video translation {project_id} uploaded as secure Private Draft.")

@app.task(name="tasks.task_cleanup_old_projects")
def task_cleanup_old_projects(project_id: str):
    db = get_db()
    if not db:
        return {"status": "failed", "error": "Database not found"}

    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        db.close()
        return {"status": "failed", "error": "Project not found"}

    try:
        project_dir = os.path.join(DATA_DIR, project_id)
        if os.path.exists(project_dir):
            for item in os.listdir(project_dir):
                item_path = os.path.join(project_dir, item)
                if item in ["output_16_9.mp4", "output_9_16.mp4"] or item.startswith("thumbnail_"):
                    continue
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)
            project.status = "cleaned"
            db.commit()
        return {"status": "cleaned"}
    except Exception as e:
        print(f"[Cleanup] Error scrubbing project directory {project_id}: {e}")
        return {"status": "failed", "error": str(e)}
    finally:
        db.close()
