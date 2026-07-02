import os
import sys
import glob

# Prevent loading incompatible system-wide CUDA DLLs by filtering them from PATH and environment on Windows
if os.name == 'nt':
    print("Running DLL Isolation code...")
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
                print(f"Adding DLL directory: {d}")
                os.add_dll_directory(d)
        
        torch_lib = os.path.join(venv_root, "Lib", "site-packages", "torch", "lib")
        if os.path.exists(torch_lib):
            print(f"Adding DLL directory: {torch_lib}")
            os.add_dll_directory(torch_lib)
            
        # Pre-import torch to force loading of the correct cuDNN/CUDA DLLs first
        import torch
        print(f"[DLL Isolation] PyTorch pre-loaded. CUDA available: {torch.cuda.is_available()}")
    except Exception as dll_err:
        print(f"[DLL Isolation Warning] Failed to configure isolated DLL paths: {dll_err}")

# Add backend directory to path
sys.path.append(os.path.abspath('backend'))

print("Initializing ThreadPoolExecutor...")
from concurrent.futures import ThreadPoolExecutor
executor = ThreadPoolExecutor(max_workers=1)

def run_in_thread():
    try:
        import voxcpm2
        print("Thread: loading VoxCPM2 model...")
        model = voxcpm2.get_model()
        print("Thread: model loaded successfully!")
    except Exception as e:
        import traceback
        print("Thread: exception occurred:")
        traceback.print_exc()

# Submit to executor
future = executor.submit(run_in_thread)
try:
    print("Waiting for thread task to complete...")
    future.result()
    print("Executor task finished successfully!")
except Exception as e:
    import traceback
    print("Main thread: task failed with exception:")
    traceback.print_exc()
