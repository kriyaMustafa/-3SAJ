import sys
import os
import gc

# Add backend to python path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from database import SessionLocal
import models
import tasks

db = SessionLocal()
project_id = "68dd1421-9391-40f8-843d-bfd5f50b6398"

# Get all translated segments
segments = db.query(models.Segment).filter(
    models.Segment.project_id == project_id,
    models.Segment.status == "translated"
).order_by(models.Segment.segment_index).all()
db.close()

print(f"Found {len(segments)} segments to synthesize.")

# Let's run a batch of up to 40 segments to see if it causes any crash or memory exhaustion
test_batch = segments[:40]
print(f"Running test loop for {len(test_batch)} segments...")

for s in test_batch:
    print(f"\n======================================")
    print(f"Synthesizing Segment index {s.segment_index} (ID {s.id})...")
    print(f"======================================")
    try:
        res = tasks.task_synthesize_tts_segment(project_id, s.id)
        print(f"Result: {res}")
    except Exception as e:
        import traceback
        print(f"Crashed on segment ID {s.id}:")
        traceback.print_exc()
        break
    
    # Clean memory
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except:
        pass

print("\nLoop batch completed!")
