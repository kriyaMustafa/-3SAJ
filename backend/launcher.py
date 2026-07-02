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

def open_browser():
    # Wait 2 seconds for the server to start before opening the browser
    time.sleep(2)
    webbrowser.open("http://127.0.0.1:8000/app")

if __name__ == "__main__":
    threading.Thread(target=open_browser, daemon=True).start()
    if getattr(sys, 'frozen', False):
        uvicorn.run(app, host="0.0.0.0", port=8000, log_config=LOGGING_CONFIG)
    else:
        # Dev/console mode: use standard uvicorn logging to avoid console logging conflicts and crash
        uvicorn.run(app, host="0.0.0.0", port=8000)