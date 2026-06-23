from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from typing import Dict
from fastapi.staticfiles import StaticFiles
import os
import sys
import time
import traceback
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from pipeline import PROCESSED_DIR, UPLOADS_DIR, run_full_pipeline_with_progress

app = FastAPI(title="Video Translation Orchestrator API")

# Add CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple in-memory status store
processing_status: Dict[str, dict] = {}

@app.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    safe_filename = os.path.basename(file.filename)
    file_path = UPLOADS_DIR / safe_filename
    
    # Write file in chunks to avoid memory issues with large videos
    with open(file_path, "wb") as buffer:
        while True:
            chunk = await file.read(1024 * 1024)  # 1MB chunks
            if not chunk:
                break
            buffer.write(chunk)
    
    # Clear previous status on new upload
    if safe_filename in processing_status:
        del processing_status[safe_filename]
        
    return {"filename": safe_filename, "status": "uploaded"}

async def execute_pipeline(filename: str, voice_cast: str = "auto"):
    safe_filename = os.path.basename(filename)
    started_at = time.time()
    processing_status[safe_filename] = {
        "step": "Queued",
        "progress": 1,
        "eta": None,
        "detail": "Waiting to start",
        "started_at": started_at,
    }

    def update_progress(event: dict):
        processing_status[safe_filename] = {
            **processing_status.get(safe_filename, {}),
            **event,
            "elapsed_seconds": round(time.time() - started_at, 1),
        }

    try:
        result = await run_full_pipeline_with_progress(safe_filename, update_progress, voice_cast)
        processing_status[safe_filename] = {
            "step": "Completed", 
            "progress": 100, 
            "eta": "0s",
            "detail": "Khmer dubbed video is ready",
            "elapsed_seconds": round(time.time() - started_at, 1),
            "result": result
        }
    except Exception as e:
        processing_status[safe_filename] = {
            "step": "Failed", 
            "progress": 0, 
            "eta": None,
            "elapsed_seconds": round(time.time() - started_at, 1),
            "error": str(e),
            "traceback": traceback.format_exc(),
        }

@app.post("/process/{filename}")
async def process_video(filename: str, background_tasks: BackgroundTasks, voice_cast: str = "auto"):
    safe_filename = os.path.basename(filename)
    background_tasks.add_task(execute_pipeline, safe_filename, voice_cast)
    return {"message": "Processing started", "filename": safe_filename, "voice_cast": voice_cast}

@app.get("/status/{filename}")
async def get_status(filename: str):
    safe_filename = os.path.basename(filename)
    return processing_status.get(safe_filename, {"step": "Not Found", "progress": 0, "eta": None})

@app.get("/download/{filename}")
async def download_video(filename: str):
    safe_filename = os.path.basename(filename)
    file_path = PROCESSED_DIR / f"translated_{safe_filename}"
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type='video/mp4', filename=f"translated_{safe_filename}")
    return {"error": "File not found"}

# Serve frontend static files AFTER API routes
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    FRONTEND_BUILD_DIR = os.path.join(sys._MEIPASS, "out")
else:
    FRONTEND_BUILD_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "out")

if os.path.exists(FRONTEND_BUILD_DIR):
    @app.get("/app")
    async def app_redirect():
        return RedirectResponse(url="/")

    # Mount the entire directory at the root / so assets and index.html match Next.js expectations
    app.mount("/", StaticFiles(directory=FRONTEND_BUILD_DIR, html=True), name="frontend")
else:
    @app.get("/")
    async def root():
        return {"message": "AI Video Translation API is running (Frontend not found)"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
