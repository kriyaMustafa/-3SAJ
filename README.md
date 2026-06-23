<<<<<<< HEAD
# Khmer AI Video Translator 🇰🇭 🤖

Professional AI-powered video dubbing pipeline that translates any video into Khmer while preserving original background sounds and matching speaker genders.

## 🚀 Key Features

- **Smart Voice Matching:** Automatically detects if the original speaker is Male, Female, or a Kid and uses the corresponding Khmer neural voice.
- **Audio Ducking:** Professional mixing that lowers original voices while keeping background music/sounds clear.
- **Turbo Processing:** Optimized for high-end CPUs (i7/i9) and NVIDIA GPUs (RTX 4060+) for fast transcription and voice generation.
- **Interactive Dashboard:** Modern web interface to monitor progress, ETA, and download results.

---

## 🛠 Prerequisites

- **Python 3.11 or 3.12** (Recommended for best GPU support).
- **Node.js 18+** (For the frontend).
- **FFmpeg:** Must be installed and added to your system PATH.

---

## 💻 Installation

### 1. Backend Setup
```powershell
# Create a virtual environment
python -m venv venv

# Activate it
.\venv\Scripts\activate

# Install dependencies
pip install -r backend/requirements.txt

# IMPORTANT: Install GPU (CUDA) support for RTX cards
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

### 2. Frontend Setup
```powershell
cd frontend
npm install
npm run build
cd ..
```

---

## 🏃 How to Run

1.  **Configure API Keys:** Open `backend/.env` and add your keys (Azure Speech is required for Khmer TTS).
2.  **Start the Server:**
    ```powershell
    .\venv\Scripts\python.exe backend/launcher.py
    ```
3.  **Open the App:** Navigate to `http://127.0.0.1:8000` in your browser.

---

## ⚙️ Resource Optimization (in `.env`)

You can tune the performance in `backend/.env`:
- `WHISPER_DEVICE`: Set to `cuda` for GPU or `cpu` for processor.
- `WHISPER_CPU_THREADS`: Increase this (e.g., `8` or `12`) to speed up processing on high-end CPUs.
- `TTS_CONCURRENCY`: Number of voices to generate at the same time.

---

## 📝 Troubleshooting

- **White Page:** If the dashboard doesn't load, press `Ctrl + F5` to clear your browser cache.
- **System Freeze:** If your PC slows down too much, lower `WHISPER_CPU_THREADS` to `4` in the `.env` file.
- **Duplicate Voices:** Ensure you are using the "Auto" or "Dual" voice modes for the best experience.

---

## 📦 How to Release (Create .exe)

To package the application into a standalone Windows program:

1.  **Build the Frontend:**
    ```powershell
    cd frontend; npm run build; cd ..
    ```
2.  **Run PyInstaller:**
    ```powershell
    cd backend
    ..\venv\Scripts\pyinstaller.exe launcher.spec --clean --noconfirm
    ```
3.  **Find your App:**
    The finished application will be in the `backend/dist/launcher/` folder. You can share this entire folder with anyone. They just need to run `launcher.exe`.
=======
# project-x1
translat video
>>>>>>> 1132aa195dc5b81277c15c34e017dfbabecac597
