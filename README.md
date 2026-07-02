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

---
# project-x1
translat video
1-use api key if api out quota system give give me transcrip with promt to use ai chat help translate and have btn for submit and make it as path have id every voice trantricp and the
    are not to big to make show ai can help  can translat
2- auto decet voice male femle and kid older 
3- make the viove to clean not nois and use only one voice to one charater for the movei drama , nad for anime recap use only one voice male or female by choising 
  ### What to do now:

  1. Re-build the frontend assets (run  npm run build  in  frontend/  directory).
  2. Run  build_exe.bat  to compile the app using PyInstaller.
  3. Once compiled, place your  VoxCPM2_Model  folder directly next to  AIVideoTranslator.exe  inside the  dist/AIVideoTranslator/  folder.
  4. Double-click the  .exe  to test. It will load completely offline, run at high speed, and maintain character voices perfectly!