import sys
import os

# Add backend to python path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

import tasks

print("Running synthesis for segment ID 26...")
try:
    res = tasks.task_synthesize_tts_segment("68dd1421-9391-40f8-843d-bfd5f50b6398", 26)
    print("Result:", res)
except Exception as e:
    import traceback
    print("Crashed:")
    traceback.print_exc()
