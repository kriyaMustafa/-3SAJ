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



import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
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
from concurrent.futures import ThreadPoolExecutor

# Create specific thread pools based on the engine's compute limits
gpu_executor = ThreadPoolExecutor(max_workers=1)     # For local GPU tasks (VoxCPM2, Demucs, Whisper)
cloud_executor = ThreadPoolExecutor(max_workers=32)  # For network/I/O bound tasks (Edge Cloud, Translate, etc.)

DATA_DIR = "/app/data" if os.path.exists("/app") else "./data"
os.makedirs(DATA_DIR, exist_ok=True)
PENDING_TASKS_FILE = os.path.abspath(os.path.join(DATA_DIR, "pending_local_tasks.json"))

def write_subprocess_task(task_name, args, kwargs):
    tasks = []
    if os.path.exists(PENDING_TASKS_FILE):
        try:
            with open(PENDING_TASKS_FILE, "r", encoding="utf-8") as f:
                tasks = json.load(f)
        except Exception:
            tasks = []
    
    tasks.append({
        "task_name": task_name,
        "args": list(args),
        "kwargs": kwargs
    })
    
    try:
        with open(PENDING_TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(tasks, f, indent=2)
    except Exception as e:
        print(f"[Queue Subprocess] Error writing pending task to file: {e}")

import queue
import json
import threading

_task_queue = queue.Queue()

import atexit
_persistent_worker = None
_persistent_worker_lock = threading.Lock()

def cleanup_persistent_worker():
    global _persistent_worker
    if _persistent_worker is not None and _persistent_worker.poll() is None:
        print("[Queue Worker] Terminating persistent task worker subprocess...")
        try:
            _persistent_worker.terminate()
            _persistent_worker.wait(timeout=2)
        except Exception:
            try:
                _persistent_worker.kill()
            except Exception:
                pass

atexit.register(cleanup_persistent_worker)

def get_persistent_worker():
    global _persistent_worker
    with _persistent_worker_lock:
        if _persistent_worker is None or _persistent_worker.poll() is not None:
            print("[Queue Worker] Starting/Restarting persistent task worker subprocess...")
            env = os.environ.copy()
            env["IS_TASK_SUBPROCESS"] = "1"
            script_path = os.path.abspath(__file__)
            _persistent_worker = subprocess.Popen(
                [sys.executable, script_path, "--persistent-worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=sys.stderr,
                text=True,
                bufsize=1,
                env=env
            )
        return _persistent_worker

def _subprocess_queue_worker():
    while True:
        item = _task_queue.get()
        if item is None:
            break
        task_name, args, kwargs = item
        try:
            # OPTIMIZATION: Run TTS synthesis tasks in-process to keep the model loaded in GPU memory,
            # bypassing the massive 30-40s process startup and weights unpickling overhead on Windows.
            # CRITICAL Windows fix: VoxCPM2 CUDA model loading inside Uvicorn's process triggers native
            # crashes. We only run TTS in-process if using non-VoxCPM2 backends (e.g. Edge Cloud).
            is_voxcpm2 = False
            if task_name in ("task_synthesize_tts_segment", "task_re_render_segment"):
                try:
                    project_id = args[0]
                    db = SessionLocal()
                    project = db.query(models.Project).filter(models.Project.id == project_id).first()
                    if project:
                        tts_backend = getattr(project, "tts_engine", "voxcpm2").strip().lower()
                        if tts_backend == "voxcpm2":
                            is_voxcpm2 = True
                    db.close()
                except Exception:
                    pass

            if task_name in ("task_synthesize_tts_segment", "task_re_render_segment") and not is_voxcpm2:
                print(f"[Queue Worker] Optimization: Executing non-VoxCPM2 task {task_name} in-process...")
                func = globals().get(task_name)
                if func:
                    func(*args, **kwargs)
                    print(f"[Queue Worker] Task {task_name} completed successfully in-process.")
                else:
                    print(f"[Queue Worker Error] Task {task_name} not found in globals!")
                continue

            env = os.environ.copy()
            env["IS_TASK_SUBPROCESS"] = "1"
            script_path = os.path.abspath(__file__)

            # Clear any pre-existing pending tasks file before running
            if os.path.exists(PENDING_TASKS_FILE):
                try:
                    os.remove(PENDING_TASKS_FILE)
                except Exception:
                    pass

            if task_name in ("task_synthesize_tts_segment", "task_re_render_segment") and is_voxcpm2:
                print(f"[Queue Worker] Executing task {task_name} in persistent worker subprocess...")
                worker = get_persistent_worker()
                payload = {"task_name": task_name, "args": list(args), "kwargs": kwargs}
                
                success = False
                try:
                    # Write task payload
                    worker.stdin.write(json.dumps(payload) + "\n")
                    worker.stdin.flush()
                    
                    # Read response (robust JSON-line parsing to skip any startup prints or warnings)
                    response = None
                    while True:
                        response_line = worker.stdout.readline()
                        if not response_line:
                            raise RuntimeError("Persistent worker subprocess died or closed stdout unexpectedly.")
                        
                        line_str = response_line.strip()
                        if not line_str:
                            continue
                        
                        try:
                            parsed = json.loads(line_str)
                            if isinstance(parsed, dict) and "status" in parsed:
                                response = parsed
                                break
                        except json.JSONDecodeError:
                            # Forward non-JSON output (like startup/isolation messages) to stderr
                            print(f"[Persistent Worker Startup/Log] {line_str}", file=sys.stderr)
                    
                    if response and response.get("status") == "success":
                        print(f"[Queue Worker] Task {task_name} completed successfully in persistent worker.")
                        success = True
                    else:
                        err_msg = response.get("error") if response else "Unknown error"
                        print(f"[Queue Worker] Task {task_name} failed in persistent worker: {err_msg}")
                except Exception as worker_exc:
                    print(f"[Queue Worker Error] Failed executing in persistent worker: {worker_exc}")
                    # Try to terminate/kill the crashed worker so it gets restarted next time
                    cleanup_persistent_worker()
                    _persistent_worker = None
                    # Fallback to isolated subprocess for safety
                    print(f"[Queue Worker] Falling back to isolated subprocess for task {task_name}...")
                    
                    serialized_payload = json.dumps({"args": list(args), "kwargs": kwargs})
                    proc = subprocess.run(
                        [sys.executable, script_path, task_name, serialized_payload],
                        env=env
                    )
                    success = (proc.returncode == 0)
            else:
                print(f"[Queue Worker] Executing task {task_name} in isolated subprocess...")
                payload = {
                    "args": list(args),
                    "kwargs": kwargs
                }
                serialized_payload = json.dumps(payload)
                
                # Inherit system output/error directly to print to parent console
                proc = subprocess.run(
                    [sys.executable, script_path, task_name, serialized_payload],
                    env=env
                )
                if proc.returncode != 0:
                    print(f"[Queue Worker] Task {task_name} failed in isolated subprocess with return code {proc.returncode}")
                else:
                    print(f"[Queue Worker] Task {task_name} completed successfully in isolated subprocess.")
            
            # Read and enqueue any tasks spawned by the subprocess
            if os.path.exists(PENDING_TASKS_FILE):
                try:
                    with open(PENDING_TASKS_FILE, "r", encoding="utf-8") as f:
                        spawned_tasks = json.load(f)
                    try:
                        os.remove(PENDING_TASKS_FILE)
                    except Exception:
                        pass
                    
                    for t in spawned_tasks:
                        t_name = t["task_name"]
                        t_args = t["args"]
                        t_kwargs = t["kwargs"]
                        print(f"[Queue Worker] Enqueuing spawned task {t_name} to main queue...")
                        _task_queue.put((t_name, t_args, t_kwargs))
                except Exception as read_err:
                    print(f"[Queue Worker] Error processing spawned tasks: {read_err}")
        except Exception as queue_err:
            print(f"[Queue Worker Exception] Error executing task {task_name}: {queue_err}")
            traceback.print_exc()
        finally:
            _task_queue.task_done()

# Start background worker only if not running as a task subprocess itself
if not os.getenv("IS_TASK_SUBPROCESS"):
    _worker_thread = Thread(target=_subprocess_queue_worker, daemon=True)
    _worker_thread.start()



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
        task_name = task.__name__
        if os.getenv("IS_TASK_SUBPROCESS") == "1":
            print(f"[Queue Subprocess] Subprocess enqueuing task {task_name} via shared file...")
            write_subprocess_task(task_name, args, kwargs)
        else:
            print(f"[Queue Local] Enqueuing task {task_name} in local subprocess queue...")
            _task_queue.put((task_name, args, kwargs))


def check_and_trigger_export(db, project_id):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project or project.status in ("exporting", "completed", "failed", "cancelled"):
        return
    
    all_segments = db.query(models.Segment).filter(models.Segment.project_id == project_id).all()
    if not all_segments:
        return
    
    all_completed = all(s.status in ("synthesized", "failed") for s in all_segments)
    has_manual_pending = any(s.status == "needs_manual_translation" for s in all_segments)
    if all_completed and not has_manual_pending:
        print(f"[Queue 4] All {len(all_segments)} segments completed (synthesized/failed). Triggering final composite and export...")
        dispatch_task(task_composite_and_export, project_id)



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
    if "stdin" not in kwargs:
        kwargs["stdin"] = subprocess.DEVNULL
        
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

        vocals_dest = os.path.join(project_dir, "vocals.wav")
        bgm_dest = os.path.join(project_dir, "bgm.wav")

        # Get audio duration using ffprobe
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            abs_audio_path
        ]
        duration = 0.0
        try:
            res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            if res.returncode == 0:
                duration = float(res.stdout.decode("utf-8").strip())
        except Exception as e:
            print(f"[Queue 1] Warning: Error querying audio duration: {e}")

        # Choose chunked processing if duration is above 15 minutes
        CHUNK_THRESHOLD = 900
        CHUNK_SIZE = 600

        if duration > CHUNK_THRESHOLD:
            num_segments = math.ceil(duration / CHUNK_SIZE)
            print(f"[Queue 1] Audio duration is {duration}s. Exceeds threshold {CHUNK_THRESHOLD}s. Running Demucs in {num_segments} chunks of {CHUNK_SIZE}s to prevent memory issues.")
            
            for j in range(num_segments):
                if is_project_cancelled(project_id):
                    print(f"[Queue 1] Project {project_id} cancelled during chunked Demucs processing. Aborting.")
                    return
                
                start_t = j * CHUNK_SIZE
                dur_t = min(CHUNK_SIZE, duration - start_t)
                segment_path = os.path.join(project_dir, f"demucs_chunk_{j}.wav")
                
                print(f"[Queue 1] Extracting chunk {j+1}/{num_segments}: start={start_t}s, duration={dur_t}s")
                split_cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(start_t),
                    "-t", str(dur_t),
                    "-i", abs_audio_path,
                    "-acodec", "copy",
                    segment_path
                ]
                subprocess.run(split_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                
                # Run Demucs on this chunk
                demucs_out_dir_j = os.path.join(project_dir, f"demucs_out_{j}")
                os.makedirs(demucs_out_dir_j, exist_ok=True)
                abs_audio_path_j = os.path.abspath(segment_path)
                abs_demucs_out_dir_j = os.path.abspath(demucs_out_dir_j)
                
                demucs_cmd_j = [
                    venv_python, "-m", "demucs",
                    "--two-stems", "vocals",
                    "--device", demucs_device,
                    "-o", abs_demucs_out_dir_j,
                    abs_audio_path_j
                ]
                
                demucs_env = os.environ.copy()
                demucs_env["PYTHONNOUSERSITE"] = "1"
                demucs_env.pop("PYTHONPATH", None)
                
                print(f"[Queue 1] Running Demucs on chunk {j+1}/{num_segments} using device={demucs_device}")
                try:
                    demucs_result = subprocess.run(
                        demucs_cmd_j,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        env=demucs_env
                    )
                    stderr_txt = demucs_result.stderr.decode("utf-8", errors="replace")
                    if demucs_result.returncode != 0 and stderr_txt.strip():
                        print(f"[Queue 1] Demucs chunk {j} stderr: {stderr_txt}")
                except Exception as run_err:
                    print(f"[Queue 1] Demucs chunk {j} execution failed: {run_err}")
                
                # Poll for outputs
                vocal_src_j = None
                bgm_src_j = None
                for _attempt in range(30):
                    for root, dirs, files in os.walk(demucs_out_dir_j):
                        for file in files:
                            if file == "vocals.wav":
                                fpath = os.path.join(root, file)
                                if os.path.getsize(fpath) > 0:
                                    vocal_src_j = fpath
                            elif file in ("no_vocals.wav", "accompaniment.wav", "background.wav"):
                                fpath = os.path.join(root, file)
                                if os.path.getsize(fpath) > 0:
                                    bgm_src_j = fpath
                    if vocal_src_j and bgm_src_j:
                        break
                    time.sleep(1)
                
                # CPU fallback for chunk
                if (not vocal_src_j or not bgm_src_j) and demucs_device == "cuda":
                    print(f"[Queue 1] WARNING: Demucs failed on CUDA for chunk {j}. Retrying on CPU...")
                    demucs_cmd_cpu = list(demucs_cmd_j)
                    try:
                        device_idx = demucs_cmd_cpu.index("--device")
                        demucs_cmd_cpu[device_idx + 1] = "cpu"
                    except Exception:
                        pass
                    
                    try:
                        demucs_result = subprocess.run(
                            demucs_cmd_cpu,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            env=demucs_env
                        )
                        vocal_src_j = None
                        bgm_src_j = None
                        for _attempt in range(30):
                            for root, dirs, files in os.walk(demucs_out_dir_j):
                                for file in files:
                                    if file == "vocals.wav":
                                        fpath = os.path.join(root, file)
                                        if os.path.getsize(fpath) > 0:
                                            vocal_src_j = fpath
                                    elif file in ("no_vocals.wav", "accompaniment.wav", "background.wav"):
                                        fpath = os.path.join(root, file)
                                        if os.path.getsize(fpath) > 0:
                                            bgm_src_j = fpath
                            if vocal_src_j and bgm_src_j:
                                break
                            time.sleep(1)
                    except Exception as cpu_err:
                        print(f"[Queue 1] Demucs CPU retry failed for chunk {j}: {cpu_err}")
                
                if not vocal_src_j or not bgm_src_j:
                    raise FileNotFoundError(f"Demucs failed to produce vocals or background audio files for chunk {j}.")
                
                # Move chunk outputs to fixed filenames
                vocals_chunk_dest = os.path.join(project_dir, f"vocals_chunk_{j}.wav")
                bgm_chunk_dest = os.path.join(project_dir, f"bgm_chunk_{j}.wav")
                shutil.move(vocal_src_j, vocals_chunk_dest)
                shutil.move(bgm_src_j, bgm_chunk_dest)
                
                # Clean up chunk inputs and temp dirs
                try:
                    os.remove(segment_path)
                    shutil.rmtree(demucs_out_dir_j, ignore_errors=True)
                except Exception as cleanup_err:
                    print(f"[Queue 1] Warning: failed to clean up temp files for chunk {j}: {cleanup_err}")
            
            # Concatenate all chunks
            print(f"[Queue 1] Concatenating vocal chunks...")
            vocals_list_file = os.path.join(project_dir, "vocals_list.txt")
            with open(vocals_list_file, "w", encoding="utf-8") as f:
                for j in range(num_segments):
                    f.write(f"file 'vocals_chunk_{j}.wav'\n")
            
            concat_vocals_cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", "vocals_list.txt",
                "-c", "copy",
                "vocals.wav"
            ]
            run_command_with_timeout(concat_vocals_cmd, timeout=300, project_id=project_id, db=db, cwd=project_dir)
            
            print(f"[Queue 1] Concatenating background music chunks...")
            bgm_list_file = os.path.join(project_dir, "bgm_list.txt")
            with open(bgm_list_file, "w", encoding="utf-8") as f:
                for j in range(num_segments):
                    f.write(f"file 'bgm_chunk_{j}.wav'\n")
            
            concat_bgm_cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", "bgm_list.txt",
                "-c", "copy",
                "bgm.wav"
            ]
            run_command_with_timeout(concat_bgm_cmd, timeout=300, project_id=project_id, db=db, cwd=project_dir)
            
            # Clean up chunks and text lists
            for j in range(num_segments):
                try:
                    os.remove(os.path.join(project_dir, f"vocals_chunk_{j}.wav"))
                    os.remove(os.path.join(project_dir, f"bgm_chunk_{j}.wav"))
                except Exception:
                    pass
            try:
                os.remove(vocals_list_file)
                os.remove(bgm_list_file)
            except Exception:
                pass
            try:
                shutil.rmtree(demucs_out_dir, ignore_errors=True)
            except Exception:
                pass

        else:
            # Run Demucs normally
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

            # CPU Fallback: If CUDA run failed (due to Out Of Memory on long files), retry on CPU
            if (not vocal_src or not bgm_src) and demucs_device == "cuda":
                print("[Queue 1] WARNING: Demucs failed on CUDA (likely Out of Memory). Retrying separation on CPU...")
                demucs_cmd_cpu = list(demucs_cmd)
                try:
                    device_idx = demucs_cmd_cpu.index("--device")
                    demucs_cmd_cpu[device_idx + 1] = "cpu"
                except Exception:
                    pass
                
                print(f"[Queue 1] Re-starting Demucs separation on CPU...")
                try:
                    demucs_result = subprocess.run(
                        demucs_cmd_cpu,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        env=demucs_env
                    )
                    print(f"[Queue 1] Demucs CPU retry exit code: {demucs_result.returncode}")
                    # Re-poll for files
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
                            print(f"[Queue 1] Demucs CPU output files ready after {_attempt}s.")
                            break
                        print(f"[Queue 1] Waiting for demucs CPU output files... attempt {_attempt+1}/30")
                        time.sleep(1)
                except Exception as cpu_err:
                    print(f"[Queue 1] Demucs CPU retry failed: {cpu_err}")

            if not vocal_src or not bgm_src:
                raise FileNotFoundError("Demucs failed to produce vocals or background audio files.")

            shutil.move(vocal_src, vocals_dest)
            shutil.move(bgm_src, bgm_dest)

        # ── Noise Cleaning Step ──
        # Apply highpass, lowpass, and FFT-based denoising to cleaned vocals
        if project.enable_noise_cleaning:
            vocals_clean_dest = os.path.join(project_dir, "vocals_clean.wav")
            noise_clean_cmd = [
                "ffmpeg", "-y",
                "-i", vocals_dest,
                "-af", "highpass=f=80,lowpass=f=8000,afftdn=nf=-25",
                vocals_clean_dest
            ]
            try:
                run_command_with_timeout(noise_clean_cmd, timeout=300, project_id=project_id, db=db)
                if os.path.exists(vocals_clean_dest) and os.path.getsize(vocals_clean_dest) > 0:
                    # Replace original vocals with cleaned version
                    shutil.move(vocals_clean_dest, vocals_dest)
                    print(f"[Queue 1] Noise cleaning applied successfully to vocals.")
                else:
                    print(f"[Queue 1] Noise cleaning output missing or empty. Using original vocals.")
            except Exception as clean_err:
                print(f"[Queue 1] Noise cleaning failed (non-fatal): {clean_err}. Using original vocals.")
        else:
            print(f"[Queue 1] Noise cleaning disabled for project {project_id}. Skipping.")

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

class MergedSegment:
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text

def merge_whisper_segments(segments, min_duration=10.0, max_duration=15.0):
    merged_list = []
    if not segments:
        return merged_list

    current_seg = None
    for seg in segments:
        if current_seg is None:
            current_seg = MergedSegment(seg.start, seg.end, seg.text.strip())
        else:
            current_duration = current_seg.end - current_seg.start
            added_duration = seg.end - current_seg.start
            
            # Merge if the current duration is less than min_duration,
            # OR if adding this segment does not exceed max_duration
            if current_duration < min_duration or added_duration <= max_duration:
                current_seg.end = seg.end
                if current_seg.text and not current_seg.text.endswith(" ") and not seg.text.startswith(" "):
                    current_seg.text += " "
                current_seg.text += seg.text.strip()
            else:
                merged_list.append(current_seg)
                current_seg = MergedSegment(seg.start, seg.end, seg.text.strip())
                
    if current_seg:
        merged_list.append(current_seg)
        
    return merged_list

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
            whisper_sz = os.getenv("WHISPER_MODEL_SIZE", "base")
            print(f"[Queue 2] Loading Whisper model size '{whisper_sz}' on: {device}")
            return WhisperModel(whisper_sz, device=device, compute_type="float16" if device == "cuda" else "int8")

        model = GPUModelManager.load_model("whisper", load_whisper)

        # ── Path normalisation fix for Windows paths with spaces ──
        # faster_whisper uses PyAV internally which fails on relative or
        # non-normalised Windows paths. Resolve to absolute path first.
        vocals_path_abs = os.path.abspath(vocals_path).replace("\\", "/")
        if not os.path.exists(vocals_path_abs):
            raise FileNotFoundError(f"[Queue 2] vocals file not found: {vocals_path_abs}")
        print(f"[Queue 2] Running Whisper transcription on: {vocals_path_abs}")
        lang = project.source_language if project.source_language and project.source_language.lower() != "auto" else None
        segments, info = model.transcribe(vocals_path_abs, beam_size=1, language=lang)
        
        # Merge segments into 10s - 20s windows to prevent short fragmented lines
        min_dur = float(os.getenv("MIN_SEGMENT_DURATION", "10.0"))
        max_dur = float(os.getenv("MAX_SEGMENT_DURATION", "15.0"))
        segment_list = merge_whisper_segments(list(segments), min_duration=min_dur, max_duration=max_dur)
        print(f"[Queue 2] Transcribed and merged into {len(segment_list)} segments. Aligning times...")

        # Load vocals audio for pitch analysis (voice gender/age detection)
        import numpy as np
        import soundfile as sf
        try:
            vocals_audio_data, vocals_sr = sf.read(vocals_path_abs)
            if len(vocals_audio_data.shape) > 1:
                vocals_audio_data = vocals_audio_data.mean(axis=1)  # Convert to mono
            print(f"[Queue 2] Loaded vocals audio for pitch analysis: {len(vocals_audio_data)} samples at {vocals_sr}Hz")
        except Exception as audio_load_err:
            print(f"[Queue 2] Could not load vocals for pitch analysis: {audio_load_err}. Voice detection will be skipped.")
            vocals_audio_data = None
            vocals_sr = 16000

        def detect_voice_type(audio_data, sr, start_time, end_time, word_count):
            """Detect voice type using fundamental frequency (F0) estimation via autocorrelation."""
            if audio_data is None:
                return 'female', 'Speaker_Female'  # Default fallback

            start_sample = int(start_time * sr)
            end_sample = int(end_time * sr)
            segment_audio = audio_data[start_sample:end_sample]

            if len(segment_audio) < sr * 0.1:  # Less than 100ms
                return 'female', 'Speaker_Female'

            # Estimate F0 using autocorrelation method
            try:
                # Windowed autocorrelation for pitch detection
                frame_size = min(len(segment_audio), int(sr * 0.03))  # 30ms frames
                if frame_size < 100:
                    return 'female', 'Speaker_Female'

                f0_estimates = []
                hop = frame_size // 2
                # Limit to analyzing at most 80 frames per segment to prevent massive CPU overhead
                total_possible_frames = len(segment_audio) // hop
                if total_possible_frames > 80:
                    hop = max(1, len(segment_audio) // 80)

                for frame_start in range(0, len(segment_audio) - frame_size, hop):
                    frame = segment_audio[frame_start:frame_start + frame_size]
                    # Remove DC offset
                    frame = frame - np.mean(frame)
                    if np.max(np.abs(frame)) < 0.01:  # Skip silent frames
                        continue

                    # Autocorrelation
                    corr = np.correlate(frame, frame, mode='full')
                    corr = corr[len(corr) // 2:]

                    # Find first peak after zero crossing (ignore lag 0)
                    min_lag = int(sr / 500)  # Max F0 = 500Hz
                    max_lag = int(sr / 60)   # Min F0 = 60Hz
                    if max_lag > len(corr):
                        max_lag = len(corr)
                    if min_lag >= max_lag:
                        continue

                    search_region = corr[min_lag:max_lag]
                    if len(search_region) == 0:
                        continue

                    peak_idx = np.argmax(search_region) + min_lag
                    if peak_idx > 0 and corr[peak_idx] > 0.3 * corr[0]:  # Confidence threshold
                        f0 = sr / peak_idx
                        if 60 <= f0 <= 500:
                            f0_estimates.append(f0)

                if not f0_estimates:
                    return 'female', 'Speaker_Female'

                median_f0 = np.median(f0_estimates)

                # Calculate speech rate (words per second) for elder detection
                duration = end_time - start_time
                speech_rate = word_count / max(duration, 0.1)

                # Classify based on F0 ranges
                if median_f0 > 300:
                    return 'kid', 'Speaker_Kid'
                elif median_f0 > 200:
                    return 'female', 'Speaker_Female'
                elif median_f0 >= 140:
                    # Ambiguous range - check speech rate for elder detection
                    if speech_rate < 2.0:  # Slower than ~2 words/sec suggests elder
                        return 'elder_female', 'Speaker_Elder_Female'
                    return 'female', 'Speaker_Female'
                else:  # F0 < 140 Hz
                    if speech_rate < 2.0:
                        return 'elder_male', 'Speaker_Elder_Male'
                    return 'male', 'Speaker_Male'

            except Exception as pitch_err:
                print(f"[Queue 2] Pitch analysis error: {pitch_err}")
                return 'female', 'Speaker_Female'

        # Process each segment and write to Database
        for idx, seg in enumerate(segment_list):
            chunk_idx = int(seg.start // 60)
            text = seg.text.strip()
            word_count = len(text.split())

            # Detect voice gender/age type
            voice_type, speaker_label = detect_voice_type(
                vocals_audio_data, vocals_sr, seg.start, seg.end, word_count
            )

            db_segment = models.Segment(
                project_id=project_id,
                chunk_index=chunk_idx,
                segment_index=idx,
                speaker_id=speaker_label,
                start_time=seg.start,
                end_time=seg.end,
                original_text=text,
                detected_voice_type=voice_type,
                status="pending"
            )
            db.add(db_segment)

        db.commit()
        print(f"[Queue 2] Transcription and voice detection completed.")

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

def translate_text_fallback(text: str, target_lang: str = "km") -> str:
    try:
        from deep_translator import GoogleTranslator
        lang_map = {
            "km": "km", "en": "en", "zh": "zh-CN", "ja": "ja", "ko": "ko", "es": "es"
        }
        mapped_lang = lang_map.get(target_lang.lower(), target_lang)
        result = GoogleTranslator(source="auto", target=mapped_lang).translate(text)
        if result and result.strip():
            return result.strip()
    except Exception as e:
        print(f"[Translation Fallback Warning] deep-translator failed: {e}")
    return ""

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

        project_dir = os.path.join(DATA_DIR, project_id)
        os.makedirs(project_dir, exist_ok=True)

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
        quota_failed = False
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
                        "Translate the transcript directly. Make it punchy, energetic, and highly concise "
                        "so the spoken translation fits the original timing. Do NOT write long summaries, "
                        "and do NOT hallucinate or add details/sentences not present in the original transcript."
                    )
                else:  # drama_recap
                    genre_instructions = (
                        f"Target language is '{target_lang}'. Focus on emotional accuracy "
                        "and dramatic storytelling, keeping the translation natural and concise within the timestamps."
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
                    "5. Translate completely—do not truncate, leave empty, or cut off sentences.\n"
                    "6. Be extremely concise. Do NOT add extra context, commentary, action descriptions, or background stories. Only translate the spoken words of the transcript."
                )

                prompt = (
                    f"{system_instruction}\n\n"
                    f"Genre context and constraints:\n{genre_instructions}\n\n"
                    f"Context (Previous translations for reference):\n{context_str}\n\n"
                    f"Translate the following text directly. Output ONLY the translated text, no quotes, no explanations, no comments:\n"
                    f"\"{current_seg.original_text}\""
                )

                translated_text = ""
                if api_key and not gemini_disabled and not quota_failed:
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
                                translated_text = ""
                            break  # Success — exit retry loop
                        except Exception as api_err:
                            err_str = str(api_err)
                            # Detect permanent quota limit first
                            if "quota" in err_str.lower() or ("limit" in err_str.lower() and "exceeded" in err_str.lower()) or "RESOURCE_EXHAUSTED" in err_str:
                                print(f"[Queue 3] Gemini API quota limit exceeded or resource exhausted: {err_str}. Switching to offline translation.")
                                quota_failed = True
                                break
                            # Detect 429 rate limit
                            elif "429" in err_str or "503" in err_str or "UNAVAILABLE" in err_str:
                                retry_delay = base_delay * (2 ** attempt)  # Exponential backoff
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
                                    print(f"[Queue 3] Gemini rate limit: all {max_retries} retries exhausted for segment {current_seg.id}.")
                                    quota_failed = True
                                    break
                            else:
                                print(f"[Queue 3] Non-retriable Gemini API error: {api_err}.")
                                quota_failed = True
                                break
                else:
                    if not quota_failed:
                        print(f"[Queue 3] Gemini API key is missing or Gemini is disabled.")
                        quota_failed = True

                if quota_failed:
                    break

                current_seg.translated_text = translated_text
                db.commit()

                # Only dispatch TTS if we actually have real translated text
                has_real_text = (
                    translated_text
                    and translated_text.strip()
                    and not translated_text.startswith("[TRANSLATION_FAILED")
                )
                if has_real_text:
                    current_seg.status = "translated"
                    db.commit()
                    dispatch_task(task_synthesize_tts_segment, project_id, current_seg.id)
                else:
                    # Mark as needs manual translation
                    duration = current_seg.end_time - current_seg.start_time
                    if duration <= 0:
                        duration = 1.0
                    recent_translations = []
                    for prev_seg in segments[:i]:
                        if prev_seg.translated_text and not prev_seg.translated_text.startswith("[TRANSLATION_FAILED"):
                            recent_translations.append(prev_seg.translated_text)
                    context_lines = recent_translations[-3:]
                    context_block = "\n".join(f"  - {line}" for line in context_lines) if context_lines else "  (No previous context available)"

                    ai_prompt = (
                        f"Translate this to Khmer naturally. Keep it concise to fit in {duration:.1f}s spoken window:\n"
                        f"\"{current_seg.original_text}\"\n\n"
                        f"Context from previous lines:\n{context_block}"
                    )

                    current_seg.ai_prompt = ai_prompt
                    current_seg.status = "needs_manual_translation"
                    current_seg.translated_text = None
                    db.commit()
                    print(f"[Queue 3] Segment {current_seg.id} marked for manual translation (ai_prompt generated).")

            except Exception as segment_err:
                tb_seg = traceback.format_exc()
                current_seg.status = "failed"
                current_seg.error_traceback = tb_seg
                current_seg.translated_text = "[TRANSLATION_FAILED: Segment Processing Error]"
                db.commit()
                import logging
                logging.error(f"Translation logic crashed for segment {current_seg.id}: {segment_err}")
                print(f"[Queue 3] Segment {current_seg.id} crashed during translation: {segment_err}")

        # Transition all remaining segments if pipeline failed early and loop did not finish
        if quota_failed and i < len(segments):
            print(f"[Queue 3] Generating manual prompts for all remaining segments...")
            # Bug Fix: Define project_dir for the manual prompt generation path.
            project_dir = os.path.join(DATA_DIR, project_id)
            for idx in range(i, len(segments)):
                rem_seg = segments[idx]
                if rem_seg.status == "needs_manual_translation":
                    continue
                # Build context
                recent_translations = []
                for prev_seg in segments[:idx]:
                    if prev_seg.translated_text and not prev_seg.translated_text.startswith("[TRANSLATION_FAILED"):
                        recent_translations.append(prev_seg.translated_text)
                context_lines = recent_translations[-3:]
                context_block = "\n".join(f"  - {line}" for line in context_lines) if context_lines else "  (No previous context available)"
                
                duration = rem_seg.end_time - rem_seg.start_time
                if duration <= 0:
                    duration = 1.0
                
                ai_prompt = (
                    f"Translate this to Khmer naturally. Keep it concise to fit in {duration:.1f}s spoken window:\n"
                    f"\"{rem_seg.original_text}\"\n\n"
                    f"Context from previous lines:\n{context_block}"
                )
                
                rem_seg.ai_prompt = ai_prompt
                rem_seg.status = "needs_manual_translation"
                rem_seg.translated_text = None
            db.commit()

        # Write manual prompts file if any segments need manual translation
        manual_segs = db.query(models.Segment).filter(
            models.Segment.project_id == project_id,
            models.Segment.status == "needs_manual_translation"
        ).order_by(models.Segment.segment_index).all()
        
        if manual_segs:
            prompts_file_path = os.path.join(project_dir, "manual_prompts.txt")
            try:
                with open(prompts_file_path, "w", encoding="utf-8") as f:
                    f.write(f"=== MANUAL TRANSLATION BATCHES FOR PROJECT: {project.name} ===\n")
                    f.write("To make translation fast and prevent context limits, the segments are divided into short parts.\n")
                    f.write("Copy the prompt for each part, paste it into ChatGPT/Claude/Gemini, and paste the results back.\n\n")
                    
                    # Split into batches by total prompt word count (target 1500 - 2000 words per copied prompt)
                    batches = []
                    current_batch = []
                    
                    # Estimate the base instruction text length (approx. 280 words)
                    base_prompt_words = 280
                    current_prompt_words = base_prompt_words
                    
                    for seg in manual_segs:
                        seg_text_words = len(seg.original_text.split()) if seg.original_text else 0
                        # Account for line prefix/suffix metadata: "Line [id] | Duration: X.Xs\nEnglish: ..." (~12 words)
                        seg_line_words = 12 + seg_text_words
                        
                        if current_batch and current_prompt_words + seg_line_words > 1700:
                            batches.append(current_batch)
                            current_batch = []
                            current_prompt_words = base_prompt_words
                            
                        current_batch.append(seg)
                        current_prompt_words += seg_line_words
                        
                    if current_batch:
                        batches.append(current_batch)
                        
                    num_batches = len(batches)
                    
                    for b_idx, batch_segs in enumerate(batches):
                        
                        f.write(f"================================================================================\n")
                        f.write(f"PART {b_idx + 1} OF {num_batches} (Segments {batch_segs[0].segment_index + 1} to {batch_segs[-1].segment_index + 1})\n")
                        f.write(f"================================================================================\n")
                        f.write("Copy the text below (from 'Act as an expert...' to 'Do not include notes'):\n\n")
                        
                        # Clean project name to get a target manga name
                        raw_name = project.name or ""
                        import re as _re
                        clean_manga_name = "[Insert Manga Name Here]"
                        if raw_name:
                            clean = _re.sub(r'\.(mp4|webm|mkv|avi|mov)$', '', raw_name, flags=_re.IGNORECASE)
                            clean = _re.sub(r'[_-]+', ' ', clean)
                            clean = _re.sub(r'(ytdown|youtube|media|720p|1080p|part|season|s\d+|eps?\d+)', '', clean, flags=_re.IGNORECASE)
                            clean = _re.sub(r'\s+', ' ', clean).strip()
                            if clean:
                                clean_manga_name = clean

                        # Combined prompt text
                        f.write("Act as an expert YouTube scriptwriter, a master storyteller, and a professional English-to-Khmer translator.\n\n")
                        f.write(f"Target Manga: {clean_manga_name}\n")
                        f.write("Target Language: Spoken Khmer\n\n")
                        f.write("Step 1: Context & Lore\n")
                        f.write(f"Before you translate, search your knowledge base for information about {clean_manga_name}. Understand the main characters' personalities, the world-building, and the current story arc so your translation perfectly matches the vibe of the manga.\n\n")
                        f.write("Step 2: Translation & Storytelling\n")
                        f.write("Translate the transcript I provide below into Khmer. However, do not just translate it word-for-word. Rewrite it into a highly addictive YouTube script following these rules:\n\n")
                        f.write("Maximum Hook & Curiosity: Structure the story to create continuous hooks and open loop curiosity gaps. Start and end segments with transitions that make the viewer ask 'what happens next?' (e.g. 'ប៉ុន្តែរឿងដែលនឹកស្មានមិនដល់គឺ...', 'តើមានអ្វីកើតឡើងបន្តទៀត?').\n\n")
                        f.write("Khmer Anime Recapper Style (សម្រាយរឿង Anime): Write strictly in the style of popular Khmer YouTube anime recappers. The tone must be like a friendly, fun, engaging MC/Host speaking directly to their fans (ហ្វេនៗ / ប្រិយមិត្ត). Rewrite the script to use popular recapper slang and expressions like 'តួឯកយើង' (our protagonist), 'អាល្អិតនេះ' (this kid), 'ខ្លាំងកប់ពពក' (insanely strong), 'ញាក់សាច់' (thrilling), 'ស្រឡាំងកាំងស្ទើរក្អួតឈាម' (stunned/vomiting blood), 'ដាច់ផ្ងារ' (shocked), 'ឡូយខ្លាំង/កប់ស៊េរី' (super cool/top tier). Do not do dry translations.\n\n")
                        f.write("High Hype and Intensity: Make action scenes sound fast-paced, epic, and legendary. Emphasize emotional spikes, drama, and conflict to keep viewers highly engaged.\n\n")
                        f.write("Natural Voiceover Style: Write in natural, spoken conversational Khmer (not stiff, formal written text). It must sound completely natural and smooth when read aloud by the narrator.\n\n")
                        f.write("Director's Notes: Include short cues in brackets, like [Pause for suspense], [Say this with a sad voice], or [High energy!], to help me narrate the video perfectly.\n\n")
                        
                        if b_idx > 0:
                            f.write("Wait until the previous part is completely finished. If you missed any line IDs from the previous part, please include their translations in this response before continuing.\n\n")
                            
                        f.write("Here is the transcript you need to translate:\n")
                        f.write("--------------------------------------------------\n")
                        for s in batch_segs:
                            duration = s.end_time - s.start_time
                            if duration <= 0:
                                 duration = 1.0
                            f.write(f"Line [{s.id}] | Duration: {duration:.1f}s\n")
                            f.write(f"English: \"{s.original_text}\"\n\n")
                        f.write("--------------------------------------------------\n\n")
                        f.write("Instructions:\n")
                        f.write("1. Translate all lines into natural Spoken Khmer using the rules above.\n")
                        f.write("2. Return ONLY the translations in this exact format (including brackets and line IDs):\n")
                        f.write("[id] <Khmer translation>\n\n")
                        f.write("3. CRITICAL: You must return exactly ONE translation line for each input ID. NEVER split a single input ID into multiple output IDs (e.g. do not turn Line [1] into [1] and [2]). If a Line contains a long paragraph or multiple sentences, translate them all together on a single line starting with that ID. Do not skip any IDs.\n\n")
                        f.write("Example:\n[1] [High energy!] ជំរាបសួរអ្នកទាំងអស់គ្នា! ថ្ងៃនេះខ្ញុំនឹងនាំអ្នកទៅកាន់ពិភពថ្មីមួយ...\n[2] [Pause for suspense] ...\n")
                        f.write("\n4. Do not include any notes, formatting, introductory text, or markdown codeblocks outside of the [id] brackets.\n\n\n")
                
                print(f"[Queue 3] API quota exceeded. Manual translation prompts saved to: {os.path.abspath(prompts_file_path)}")
            except Exception as file_err:
                print(f"[Queue 3] Failed to write manual_prompts.txt file: {file_err}")

            project.status = "needs_manual_translation"
            db.commit()
            return {"status": "needs_manual_translation", "manual_count": len(manual_segs)}
        else:
            project.status = "synthesizing"
            db.commit()
            check_and_trigger_export(db, project_id)
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
        
        # Determine TTS backend from project settings, fallback to env var
        tts_backend = getattr(project, "tts_engine", os.getenv("TTS_BACKEND", "voxcpm2")).strip().lower()

        # VRAM Cycle load: Ensure the TTS model is loaded only if using voxcpm2.
        if tts_backend == "voxcpm2":
            def load_tts_model():
                import voxcpm2
                print("[Queue 4] Loading VoxCPM2 Voice Synthesis engine.")
                return voxcpm2.get_model()
            
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
            check_and_trigger_export(db, project_id)
            return {"status": "skipped", "reason": "no_valid_translation", "audio_path": final_wav}

        tts_success = False

        # Clean text to synthesize (remove bracketed tags like [Khmer Dub] or unclosed [Khmer)
        synth_text = segment.translated_text
        if synth_text:
            synth_text = re.sub(r'\[.*?\]', '', synth_text)
            synth_text = re.sub(r'^\[[^\]]*$', '', synth_text)
            synth_text = synth_text.strip()
        if not synth_text:
            synth_text = " "

        # ── Voice Profile Resolution ──
        # Check voice mapping file for consistency if speaker is registered there
        voice_mapping_path = os.path.join(project_dir, "voice_mapping.json")
        voice_mapping = {}
        if os.path.exists(voice_mapping_path):
            try:
                with open(voice_mapping_path, "r", encoding="utf-8") as vmf:
                    voice_mapping = json.load(vmf)
            except Exception:
                pass

        effective_speaker_id = segment.speaker_id or "Speaker_Female"

        # Auto-detect or resolve effective voice type
        effective_voice_type = segment.detected_voice_type or "female"

        # Apply voice mapping override if defined for this speaker
        if effective_speaker_id in voice_mapping:
            effective_voice_type = voice_mapping[effective_speaker_id].get("voice", effective_voice_type)
        else:
            # Register this speaker's voice profile for consistency
            voice_profile_entry = {
                "voice": effective_voice_type,
                "rate": "+0%",
                "pitch": "+0Hz"
            }
            # Set rate/pitch adjustments to strictly neutral/flat for absolute consistency.
            voice_profile_entry["rate"] = "+0%"
            voice_profile_entry["pitch"] = "+0Hz"

            voice_mapping[effective_speaker_id] = voice_profile_entry
            try:
                os.makedirs(project_dir, exist_ok=True)
                with open(voice_mapping_path, "w", encoding="utf-8") as vmf:
                    json.dump(voice_mapping, vmf, indent=2, ensure_ascii=False)
                print(f"[Queue 4] Registered new voice mapping for {effective_speaker_id}: {voice_profile_entry}")
            except Exception as vm_write_err:
                print(f"[Queue 4] Error saving voice_mapping.json: {vm_write_err}")

        # TASK 3: Anime Recap — single narrator voice override
        if project.genre_mode == "anime_recap":
            narrator = project.narrator_voice or "male"
            effective_voice_type = narrator
            effective_speaker_id = f"Speaker_{narrator.capitalize()}"
            print(f"[Queue 4] Anime recap mode: override using single narrator voice '{narrator}' for all segments.")

        if tts_backend == "voxcpm2":
            try:
                import sys
                sys.path.append(os.path.dirname(os.path.abspath(__file__)))
                import voxcpm2
                print(f"[Queue 4] Using VoxCPM2 for synthesis of segment {segment.segment_index}...")
                # Map effective_voice_type to VoxCPM2 profile
                profile = "female"
                if effective_voice_type in ("male", "elder_male"):
                    profile = "male"
                elif effective_voice_type == "kid":
                    profile = "kid"

                orig_dur = segment.end_time - segment.start_time
                if orig_dur <= 0:
                    orig_dur = 1.0
                voxcpm2.generate(
                    text=synth_text,
                    output_path=output_wav,
                    voice_profile=profile,
                    target_lang=project.target_language,
                    original_duration=orig_dur
                )
                tts_success = os.path.exists(output_wav)
            except Exception as vox_exc:
                print(f"[Queue 4] VoxCPM2 synthesis failed: {vox_exc}. Falling back to edge-tts.")
                tts_success = False


        if not tts_success:
            # Run Edge-TTS (either as fallback or primary)
            # Voice profile mapping with elder support (TASK 2 + TASK 3)
            voice_profiles = {
                "male": {"voice": "km-KH-PisethNeural", "rate": "+0%", "pitch": "+0Hz"},
                "female": {"voice": "km-KH-SreymomNeural", "rate": "+0%", "pitch": "+0Hz"},
                "kid": {"voice": "km-KH-SreymomNeural", "rate": "+5%", "pitch": "+6Hz"},
                "elder_male": {"voice": "km-KH-PisethNeural", "rate": "-2%", "pitch": "-4Hz"},
                "elder_female": {"voice": "km-KH-SreymomNeural", "rate": "-2%", "pitch": "-2Hz"},
            }

            # Get voice profile, with voice_mapping overrides
            voice_config = voice_profiles.get(effective_voice_type, voice_profiles["female"])

            # Apply any custom rate/pitch from voice_mapping.json
            if os.path.exists(os.path.join(project_dir, "voice_mapping.json")):
                try:
                    with open(os.path.join(project_dir, "voice_mapping.json"), "r", encoding="utf-8") as vmf:
                        vm = json.load(vmf)
                    if effective_speaker_id in vm:
                        mapped_profile = vm[effective_speaker_id]
                        base_voice_type = mapped_profile.get("voice", effective_voice_type)
                        voice_config = voice_profiles.get(base_voice_type, voice_profiles["female"]).copy()
                        voice_config["rate"] = mapped_profile.get("rate", voice_config["rate"])
                        voice_config["pitch"] = mapped_profile.get("pitch", voice_config["pitch"])
                except Exception:
                    pass

            voice_gender_neural = voice_config["voice"]
            edge_rate = voice_config["rate"]
            edge_pitch = voice_config["pitch"]

            # Run Edge-TTS in-process using the edge-tts Python library to avoid Windows command line length limits (WinError 206)
            import asyncio
            import edge_tts

            async def run_edge_tts_async():
                communicate = edge_tts.Communicate(
                    text=synth_text,
                    voice=voice_gender_neural,
                    rate=edge_rate,
                    pitch=edge_pitch
                )
                await communicate.save(output_wav)

            # Retry mechanism for robust network calls (transient failures/rate limits)
            max_retries = 3
            edge_tts_success = False
            for attempt in range(1, max_retries + 1):
                try:
                    asyncio.run(run_edge_tts_async())
                    if os.path.exists(output_wav) and os.path.getsize(output_wav) > 0:
                        edge_tts_success = True
                        break
                    else:
                        raise FileNotFoundError("Output file is empty or not created")
                except Exception as edge_exc:
                    print(f"[Queue 4] Edge-TTS attempt {attempt}/{max_retries} failed for segment {segment.segment_index}: {edge_exc}")
                    if attempt < max_retries:
                        # Exponential backoff: sleep 1.5s, 3s...
                        time.sleep(attempt * 1.5)

            if not edge_tts_success:
                print(f"[Queue 4] Edge-TTS failed after {max_retries} attempts. Writing fallback silent wave.")
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

        # To prevent the video moving faster than the sound, we must allow the audio 
        # to speed up enough to fit the original duration perfectly.
        max_speed = float(os.getenv("MAX_SPEED_MULTIPLIER", "1.3"))
        atempo_val = max(0.9, min(max_speed, speed_multiplier))
        filter_str = f"atempo={atempo_val:.4f},volume=1.2"
        stretch_cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-i", output_wav,
            "-filter:a", filter_str,
            final_wav
        ]
        subprocess.run(stretch_cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        segment.audio_path = final_wav
        segment.status = "synthesized"
        
        # Update segment.end_time to reflect actual synthesized duration
        # so subtitles match and assembly track doesn't cut off early.
        actual_synth_duration = synth_duration / atempo_val
        if actual_synth_duration > original_duration:
            segment.extended_duration = actual_synth_duration - original_duration
            segment.end_time = segment.start_time + actual_synth_duration
            
        db.commit()
        print(f"[Queue 4] Segment {segment.segment_index} time-stretched successfully (atempo={atempo_val:.2f}).")

        # Compile check
        check_and_trigger_export(db, project_id)

        return {"status": "success", "audio_path": final_wav}

    except Exception as e:
        tb = traceback.format_exc()
        segment.status = "failed"
        segment.error_traceback = tb
        db.commit()
        print(f"[Queue 4] TTS synthesis failed for segment {segment_id}: {tb}")
        check_and_trigger_export(db, project_id)
        return {"status": "failed", "error": str(e), "traceback": tb}
    finally:
        db.close()
        # Free CUDA memory cache and trigger garbage collection to prevent Windows VRAM paging
        try:
            import gc
            import torch
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

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

        # Build video slowdown filtergraph based on original timestamps
        filter_lines = []
        concat_labels = ""
        v_idx = 0
        last_orig_vid_time = 0.0
        has_video_stretch = False
        
        for s in segments:
            ext_dur = getattr(s, 'extended_duration', 0.0)
            if ext_dur > 0.05:
                has_video_stretch = True
                orig_dur = (s.end_time - s.start_time) - ext_dur
                orig_start = max(s.start_time, last_orig_vid_time)
                orig_end = max(s.start_time + orig_dur, orig_start + 0.1)
                
                if orig_start > last_orig_vid_time:
                    filter_lines.append(f"[0:v]trim=start={last_orig_vid_time}:end={orig_start},setpts=PTS-STARTPTS[v{v_idx}];")
                    concat_labels += f"[v{v_idx}]"
                    v_idx += 1
                
                slow_factor = (orig_end - orig_start + ext_dur) / (orig_end - orig_start)
                filter_lines.append(f"[0:v]trim=start={orig_start}:end={orig_end},setpts={slow_factor}*(PTS-STARTPTS)[v{v_idx}];")
                concat_labels += f"[v{v_idx}]"
                v_idx += 1
                
                last_orig_vid_time = orig_end
                
        if has_video_stretch:
            filter_lines.append(f"[0:v]trim=start={last_orig_vid_time},setpts=PTS-STARTPTS[v{v_idx}];")
            concat_labels += f"[v{v_idx}]"
            v_idx += 1

        # Push overlapping segments forward to maintain natural gaps and prevent audio collision.
        # This will organically extend the final video if the audio overflows.
        current_time = 0.0
        for s in segments:
            duration = s.end_time - s.start_time
            s.start_time = max(s.start_time, current_time)
            s.end_time = s.start_time + duration
            current_time = s.end_time

        # 1. Subtitles (.ass format)
        ass_path = os.path.join(project_dir, "subtitles.ass")
        write_ass_subtitles(ass_path, segments)

        # 2. Vocal mix & ducking BGM
        mixed_audio_path = os.path.join(project_dir, "final_dubbed_audio.wav")
        vocals_mix_path = os.path.join(project_dir, "vocals_mix.wav")

        if os.path.exists(mixed_audio_path) and os.path.getsize(mixed_audio_path) > 1000000:
            print(f"[Queue 5] Final dubbed audio already exists ({os.path.getsize(mixed_audio_path)} bytes). Skipping mix stage.")
        else:
            assemble_vocals_track(vocals_mix_path, segments)

            if project.enable_background_sound and project.bgm_path and os.path.exists(project.bgm_path):
                print(f"[Queue 5] Background sound enabled. Mixing with BGM ducking...")
                ducking_filter = (
                    f"[1:a]volume=2.5,asplit[v_duck][v_direct];"
                    f"[0:a]volume=0.4[bgm_quiet];"
                    f"[bgm_quiet][v_duck]sidechaincompress=threshold=0.1:ratio=4:attack=50:release=300:makeup=1.0[bgm_ducked];"
                    f"[bgm_ducked][v_direct]amix=inputs=2:duration=first:dropout_transition=2[a_mixed_raw];"
                    f"[a_mixed_raw]volume=2.0[a_mixed]"
                )
                duck_cmd = [
                    "ffmpeg", "-y", "-nostdin",
                    "-i", project.bgm_path,
                    "-i", vocals_mix_path,
                    "-filter_complex", ducking_filter,
                    "-map", "[a_mixed]",
                    mixed_audio_path
                ]
                subprocess.run(duck_cmd, stdin=subprocess.DEVNULL, check=True)
            else:
                print(f"[Queue 5] Background sound disabled or missing. Using vocals track only.")
                copy_cmd = [
                    "ffmpeg", "-y", "-nostdin",
                    "-i", vocals_mix_path,
                    "-filter:a", "volume=2.5",
                    "-c:a", "pcm_s16le",
                    mixed_audio_path
                ]
                subprocess.run(copy_cmd, stdin=subprocess.DEVNULL, check=True)

        # Convert path to forward slashes and escape backslashes/colons for ffmpeg filters on Windows
        ffmpeg_ass_path = ass_path.replace("\\", "/")
        if ":" in ffmpeg_ass_path:
            ffmpeg_ass_path = ffmpeg_ass_path.replace(":", "\\:")

        # Check if CUDA is available for GPU accelerated encoding/decoding
        import torch
        gpu_decode_args = []
        if not has_video_stretch and not getattr(project, "enable_subtitles", True):
            print("[Queue 5] No subtitles and no video stretch. Using stream copy for video (instant).")
            video_encoder = ["-c:v", "copy"]
            shorts_encoder = ["-c:v", "copy"]
        elif torch.cuda.is_available():
            print("[Queue 5] CUDA GPU detected. Using h264_nvenc for fast video encoding.")
            video_encoder = ["-c:v", "h264_nvenc", "-preset", "p1", "-rc", "vbr", "-cq", "22"]
            shorts_encoder = ["-c:v", "h264_nvenc", "-preset", "p1", "-rc", "vbr", "-cq", "20"]
            gpu_decode_args = ["-hwaccel", "cuda"]
        else:
            print("[Queue 5] CUDA GPU not available or not active. Falling back to libx264 CPU encoding.")
            video_encoder = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "22"]
            shorts_encoder = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "20"]

        # Transcode source video to a fast intermediate format to speed up the complex filtergraph seek/decode
        fast_video_path = project.video_path
        temp_fast_video = None
        if has_video_stretch:
            print("[Queue 5] Pre-transcoding video to fast-seeking H.264 intermediate...")
            temp_fast_video = os.path.join(project_dir, "temp_fast_decode.mp4")
            
            # Use GPU if available, fallback to CPU
            if torch.cuda.is_available():
                transcode_cmd = [
                    "ffmpeg", "-y", "-nostdin",
                    "-hwaccel", "cuda",
                    "-i", project.video_path,
                    "-c:v", "h264_nvenc", "-preset", "p1",
                    "-g", "15", "-keyint_min", "15", # Short GOP for fast seeking
                    "-an", # Drop audio for speed and space
                    temp_fast_video
                ]
            else:
                transcode_cmd = [
                    "ffmpeg", "-y", "-nostdin",
                    "-i", project.video_path,
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-g", "15", "-keyint_min", "15", # Short GOP
                    "-an",
                    temp_fast_video
                ]
            try:
                subprocess.run(transcode_cmd, stdin=subprocess.DEVNULL, check=True)
                fast_video_path = temp_fast_video
                print("[Queue 5] Fast intermediate video created successfully.")
            except Exception as trans_err:
                print(f"[Queue 5] Pre-transcoding failed: {trans_err}. Using original video.")

        # 3. Output 16:9 MP4 Video
        output_16_9 = os.path.join(project_dir, "output_16_9.mp4")
        
        if has_video_stretch:
            # We must apply the ass filter on top of the stitched/stretched video
            if getattr(project, "enable_subtitles", True):
                filter_lines.append(f"{concat_labels}concat=n={v_idx}:v=1:a=0[vout];[vout]ass='{ffmpeg_ass_path}'[final_v]")
            else:
                filter_lines.append(f"{concat_labels}concat=n={v_idx}:v=1:a=0[final_v]")
                
            filter_script_path = os.path.join(project_dir, "video_stretch_filter.txt")
            with open(filter_script_path, "w", encoding="utf-8") as f:
                f.write("\n".join(filter_lines))
            
            video_filters_args = [
                "-filter_complex_script", filter_script_path,
                "-map", "[final_v]",
                "-map", "1:a"
            ]
        else:
            if getattr(project, "enable_subtitles", True):
                video_filters_args = [
                    "-map", "0:v",
                    "-map", "1:a",
                    "-vf", f"ass='{ffmpeg_ass_path}'"
                ]
            else:
                video_filters_args = [
                    "-map", "0:v",
                    "-map", "1:a"
                ]

        video_cmd = [
            "ffmpeg", "-y", "-nostdin",
        ] + gpu_decode_args + [
            "-i", fast_video_path,
            "-i", mixed_audio_path,
        ] + video_filters_args + video_encoder + [
            "-c:a", "aac",
            "-b:a", "192k",
            output_16_9
        ]
        subprocess.run(video_cmd, stdin=subprocess.DEVNULL, check=True)

        # Cleanup intermediate video
        if temp_fast_video and os.path.exists(temp_fast_video):
            try:
                os.remove(temp_fast_video)
            except Exception as clean_err:
                print(f"[Queue 5] Could not remove temp_fast_decode: {clean_err}")

        project.output_video_16_9 = output_16_9
        db.commit()

        # 4. Exporter 9:16 Shorts
        if project.generate_shorts:
            output_9_16 = os.path.join(project_dir, "output_9_16.mp4")
            best_start, best_end = find_highest_density_window(segments, window_size=60)
            
            crop_cmd = [
                "ffmpeg", "-y", "-nostdin",
                "-ss", str(best_start),
                "-t", "60",
                "-i", output_16_9,
                "-vf", "crop=ih*9/16:ih:(iw-ow)/2:0,scale=1080:1920",
            ] + shorts_encoder + [
                "-c:a", "copy",
                output_9_16
            ]
            subprocess.run(crop_cmd, stdin=subprocess.DEVNULL, check=True)
            project.output_video_9_16 = output_9_16
            db.commit()

        # 5. Engagement Thumbnails
        capture_and_score_thumbnails(project_id, project.video_path, db)

        # 6. Boilerplates upload
        trigger_mock_social_shares(project_id)

        project.status = "completed"
        db.commit()

        # Schedule 24h cleanup
        if is_redis_running():
            try:
                task_cleanup_old_projects.apply_async(args=[project_id], countdown=86400)
            except Exception as e:
                print(f"[Queue 5] Warning: Failed to schedule cleanup task: {e}")
        else:
            print("[Queue 5] Redis offline. Skipping delayed cleanup task scheduling.")

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
            if txt.startswith("[TRANSLATION_FAILED"):
                txt = ""
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

    current_time = 0.0
    for s in segments:
        if s.audio_path and os.path.exists(s.audio_path):
            try:
                data, sample_rate = sf.read(s.audio_path)
                if sample_rate != sr:
                    import librosa
                    data = librosa.resample(data, orig_sr=sample_rate, target_sr=sr)
                
                # Push the start time forward if the previous segment overflowed
                actual_start = max(s.start_time, current_time)
                start_sample = int(actual_start * sr)
                end_sample = start_sample + len(data)
                
                # Dynamically expand the vocal_data array if the audio pushes past the initial max_end estimation
                if end_sample > len(vocal_data):
                    padding = np.zeros(end_sample - len(vocal_data), dtype=np.float32)
                    vocal_data = np.concatenate((vocal_data, padding))
                    
                vocal_data[start_sample:end_sample] += data
                
                # Update current_time to the end of this segment
                current_time = actual_start + (len(data) / sr)
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

    step = max(30.0, duration / 15.0)
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
        subprocess.run(shot_cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(thumb_path):
            # Fast mock scoring (disabled Gemini API for speed)
            import random
            score = round(random.uniform(50.0, 95.0), 1)

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
    """Mock function to simulate social media sharing."""
    print(f"[Queue 5] Mocking social media shares for project {project_id}...")
    pass

@app.task(name="tasks.task_cleanup_old_projects")
def task_cleanup_old_projects(project_id: str):
    """Scheduled task to clean up old projects."""
    print(f"[Queue 5] Scheduled cleanup for project {project_id}")
    pass

if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) > 1 and sys.argv[1] == "--persistent-worker":
        # We are the persistent worker process!
        os.environ["IS_TASK_SUBPROCESS"] = "1"
        
        # Redirect standard output to standard error to avoid polluting the stdout channel
        # which is used for communicating task execution status with the parent process.
        original_stdout = sys.stdout
        sys.stdout = sys.stderr
        
        print("[Persistent Worker] Started and listening on stdin...", file=sys.stderr)
        
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    print("[Persistent Worker] stdin closed. Exiting.", file=sys.stderr)
                    break
                
                payload = json.loads(line.strip())
                task_name = payload.get("task_name")
                args = payload.get("args", [])
                kwargs = payload.get("kwargs", {})
                
                func = globals().get(task_name)
                if func:
                    print(f"[Persistent Worker] Executing task {task_name}...", file=sys.stderr)
                    func(*args, **kwargs)
                    print(f"[Persistent Worker] Completed task {task_name}.", file=sys.stderr)
                    status_payload = {"status": "success", "task_name": task_name}
                else:
                    print(f"[Persistent Worker Error] Task {task_name} not found in tasks.py!", file=sys.stderr)
                    status_payload = {"status": "error", "error": f"Task {task_name} not found"}
            except Exception as e:
                print(f"[Persistent Worker Exception] {e}", file=sys.stderr)
                import traceback
                traceback.print_exc(file=sys.stderr)
                status_payload = {"status": "error", "error": str(e)}
                
            try:
                original_stdout.write(json.dumps(status_payload) + "\n")
                original_stdout.flush()
            except Exception as write_err:
                print(f"[Persistent Worker] Error writing response: {write_err}", file=sys.stderr)
        sys.exit(0)
    elif len(sys.argv) > 2:
        task_name = sys.argv[1]
        payload_str = sys.argv[2]
        try:
            payload = json.loads(payload_str)
            args = payload.get("args", [])
            kwargs = payload.get("kwargs", {})
            
            # Set the environment variable so imported modules know it's a subprocess
            os.environ["IS_TASK_SUBPROCESS"] = "1"
            
            # Find the function in globals
            func = globals().get(task_name)
            if func:
                print(f"[Subprocess Task Runner] Executing {task_name} with args={args} kwargs={kwargs}...")
                func(*args, **kwargs)
                print(f"[Subprocess Task Runner] Finished {task_name}.")
                sys.exit(0)
            else:
                print(f"[Subprocess Task Runner Error] Task {task_name} not found in tasks.py!")
                sys.exit(1)
        except Exception as e:
            print(f"[Subprocess Task Runner Exception] {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)