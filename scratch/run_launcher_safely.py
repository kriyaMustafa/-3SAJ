import os
import sys
import traceback

# Add backend directory to path
sys.path.append(os.path.abspath('backend'))

# Prevent loading incompatible system-wide CUDA DLLs
if os.name == 'nt':
    for k in list(os.environ.keys()):
        if "CUDA_PATH" in k.upper():
            os.environ.pop(k, None)
    _paths = os.environ.get("PATH", "").split(";")
    _filtered = [p for p in _paths if "NVIDIA GPU Computing Toolkit" not in p]
    os.environ["PATH"] = ";".join(_filtered)
    try:
        venv_root = os.path.dirname(os.path.abspath(__file__)) # relative to scratch
        venv_root = os.path.dirname(venv_root) # project root
        venv_path = os.path.join(venv_root, "venv")
        import glob
        nvidia_dirs = glob.glob(os.path.join(venv_path, "Lib", "site-packages", "nvidia", "*", "bin"))
        for d in nvidia_dirs:
            if os.path.exists(d):
                os.add_dll_directory(d)
        torch_lib = os.path.join(venv_path, "Lib", "site-packages", "torch", "lib")
        if os.path.exists(torch_lib):
            os.add_dll_directory(torch_lib)
    except Exception as e:
        print(f"DLL isolation warning: {e}")

try:
    print("Importing app from main...")
    from main import app
    import uvicorn
    
    print("Starting Uvicorn server...")
    # Wrap in try-except
    try:
        # Run uvicorn without custom logging config so we see everything
        uvicorn.run(app, host="0.0.0.0", port=8000)
    except BaseException as be:
        print("Uvicorn was stopped or raised BaseException:")
        traceback.print_exc()
        with open("scratch/launcher_crash.log", "w") as f:
            f.write("BaseException caught:\n")
            traceback.print_exc(file=f)
except Exception as e:
    print("Main exception:")
    traceback.print_exc()
    with open("scratch/launcher_crash.log", "w") as f:
        f.write("Exception caught:\n")
        traceback.print_exc(file=f)
