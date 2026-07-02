import sys
import os
import webbrowser
import threading
import time
import uvicorn
import importlib.metadata

# Robust fix for uvicorn crash in windowed mode (no console)
class NullWriter:
    def write(self, data): pass
    def flush(self): pass
    def isatty(self): return False

if sys.stdout is None: sys.stdout = NullWriter()
if sys.stderr is None: sys.stderr = NullWriter()

# Safe uvicorn logging config for windowed mode
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "%(levelname)s: %(message)s"},
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO"},
    },
}

# Fix for imageio/moviepy metadata issues in packaged executables
if getattr(sys, 'frozen', False):
    original_version = importlib.metadata.version
    def patched_version(package_name):
        try: return original_version(package_name)
        except importlib.metadata.PackageNotFoundError: return "0.0.0"
    importlib.metadata.version = patched_version

from main import app

def open_as_app(url):
    import subprocess
    import shutil
    
    # Paths to search for Chrome/Edge executable on Windows
    paths = [
        # Chrome paths
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        # Edge paths
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    
    # Check if chrome or msedge is available in PATH
    for cmd in ["chrome", "msedge", "google-chrome", "microsoft-edge"]:
        path = shutil.which(cmd)
        if path:
            paths.insert(0, path)
            
    # Try to launch the first browser found in app mode
    for p in paths:
        if os.path.exists(p):
            try:
                subprocess.Popen([p, f"--app={url}"])
                print(f"🚀 Launched standalone app window using: {p}")
                return True
            except Exception:
                pass
                
    return False

def open_browser():
    # Wait 2.5 seconds for the server to start before opening
    time.sleep(2.5)
    url = "http://127.0.0.1:8000/"
    
    # Try launching as a chromeless standalone app window
    launched = False
    try:
        launched = open_as_app(url)
    except Exception as e:
        print(f"Error launching app window: {e}")
        
    # Fallback to standard web browser tab if app mode launch fails
    if not launched:
        print("⚠️ Standalone app window launch failed. Falling back to default web browser.")
        webbrowser.open(url)

if __name__ == "__main__":
    threading.Thread(target=open_browser, daemon=True).start()
    if getattr(sys, 'frozen', False):
        uvicorn.run(app, host="0.0.0.0", port=8000, log_config=LOGGING_CONFIG)
    else:
        # Dev/console mode: use standard uvicorn logging to avoid console logging conflicts and crash
        uvicorn.run(app, host="0.0.0.0", port=8000)