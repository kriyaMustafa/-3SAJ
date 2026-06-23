# AI Video Translation Orchestrator & Product Designer

## Objective
Take an imported video, manage a high-fidelity Khmer translation pipeline, and orchestrate a modern, interactive UX/UI dashboard for the user to review, edit, and export the final 100% dubbed Khmer video.

## Architecture

### Stage 1: Backend Translation Pipeline (Python)
- **Speaker Diarization & Gender Detection:** `PyAnnote.audio` or `AssemblyAI API`.
- **Speech-to-Text & Timestamping:** `OpenAI Whisper` (Faster-Whisper).
- **Contextual Khmer Translation:** `Claude 3.5 Sonnet` or `GPT-4o`.
- **Professional Khmer TTS & Pacing:** `Microsoft Azure TTS` (`km-KH-PisethNeural`, `km-KH-SreymomNeural`).
- **Audio Mixing & Ducking:** `FFmpeg` / `MoviePy`.

### Stage 2: UX/UI Interface (Next.js + Tailwind + Shadcn/ui)
- **Panel A: Media Player** (Preview, Toggle Audio, Khmer Subtitles).
- **Panel B: Interactive Workspace** (Timestamped Transcript Editor, Speaker Gender/Style Overrides).
- **Panel C: Status & Export** (Progress Bars, Export MP4/MP3/SRT).

## Project Structure
- `backend/`: FastAPI application handling the pipeline.
- `frontend/`: Next.js application for the dashboard.
- `data/`: Storage for uploads and processed assets.
