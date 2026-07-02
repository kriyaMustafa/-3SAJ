import os
import sys

# Add backend directory to path
sys.path.append(os.path.abspath('backend'))

from database import SessionLocal
import models

db = SessionLocal()
try:
    projects = db.query(models.Project).all()
    print(f"Total projects: {len(projects)}")
    for p in projects:
        print(f"Project ID: {p.id}")
        print(f"  Name: {p.name}")
        print(f"  Status: {p.status}")
        print(f"  Genre Mode: {p.genre_mode}")
        print(f"  TTS Engine: {getattr(p, 'tts_engine', 'N/A')}")
        
        # Count segments
        total_segments = db.query(models.Segment).filter(models.Segment.project_id == p.id).count()
        translated_segments = db.query(models.Segment).filter(
            models.Segment.project_id == p.id,
            models.Segment.status == "translated"
        ).count()
        synthesized_segments = db.query(models.Segment).filter(
            models.Segment.project_id == p.id,
            models.Segment.status == "synthesized"
        ).count()
        print(f"  Segments: {total_segments} total, {translated_segments} translated, {synthesized_segments} synthesized")
except Exception as e:
    import traceback
    traceback.print_exc()
finally:
    db.close()
