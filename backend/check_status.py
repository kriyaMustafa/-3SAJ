"""Quick status check for the latest project."""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
from database import SessionLocal
import models

PROJECT_ID = sys.argv[1] if len(sys.argv) > 1 else None

db = SessionLocal()
if PROJECT_ID:
    projects = db.query(models.Project).filter(models.Project.id == PROJECT_ID).all()
else:
    projects = db.query(models.Project).order_by(models.Project.id.desc()).limit(3).all()

for p in projects:
    segs = db.query(models.Segment).filter(models.Segment.project_id == p.id).all()
    translated = [s for s in segs if s.translated_text and not s.translated_text.startswith("[TRANSLATION_FAILED")]
    synth = [s for s in segs if s.status == "synthesized"]
    print(f"\nProject: {p.id[:8]}... | Name: {p.name} | Status: {p.status}")
    print(f"  Chunks: {len(db.query(models.VideoChunk).filter(models.VideoChunk.project_id==p.id).all())}")
    print(f"  Segments: {len(segs)} | Translated: {len(translated)}/{len(segs)} | Synthesized: {len(synth)}/{len(segs)}")
    if translated:
        print("  Sample translations:")
        for s in translated[:4]:
            txt = (s.translated_text or "")[:70].replace("\n", " ")
            print(f"    [{s.segment_index:3d}] {txt}")
db.close()
