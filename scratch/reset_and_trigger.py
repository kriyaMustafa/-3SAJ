import os
import sys
import glob
import urllib.request
import json

# Add backend to path
sys.path.append(os.path.abspath('backend'))

from database import SessionLocal
import models

PROJECT_ID = '757d3433-2453-4478-b497-abc0c1c50fa0'

def main():
    db = SessionLocal()
    try:
        project = db.query(models.Project).filter(models.Project.id == PROJECT_ID).first()
        if not project:
            print(f"Project {PROJECT_ID} not found.")
            return
        
        print(f"Resetting project '{project.name}' ({PROJECT_ID}) to synthesizing...")
        project.status = 'synthesizing'
        
        # Reset segments
        segments = db.query(models.Segment).filter(models.Segment.project_id == PROJECT_ID).all()
        for s in segments:
            s.status = 'translated'
            s.audio_path = None
        db.commit()
        print(f"Reset {len(segments)} segments to 'translated' status.")
        
        # Delete old files
        project_dir = os.path.join('data', PROJECT_ID)
        if os.path.exists(project_dir):
            # delete all segment_*.wav files
            pattern_tts = os.path.join(project_dir, "segment_*_tts.wav")
            pattern_final = os.path.join(project_dir, "segment_*_final.wav")
            files_to_remove = glob.glob(pattern_tts) + glob.glob(pattern_final)
            for f in files_to_remove:
                try:
                    os.remove(f)
                except Exception as e:
                    print(f"Error removing {f}: {e}")
            print(f"Deleted {len(files_to_remove)} old audio segment files.")
            
        # Try to trigger the rendering via API calls
        print("Sending API requests to trigger synthesis on the running server...")
        triggered_count = 0
        failed_count = 0
        for s in segments:
            url = f"http://127.0.0.1:8000/api/projects/{PROJECT_ID}/segments/{s.id}/render"
            req = urllib.request.Request(url, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=1) as resp:
                    if resp.status == 200:
                        triggered_count += 1
            except Exception:
                failed_count += 1
                
        print(f"Triggered rendering for {triggered_count} segments via API. ({failed_count} failed to connect/trigger)")
        if failed_count > 0:
            print("\n[NOTE] If the server was not running or has not been restarted, please restart it using 'Start.bat'.")
            print("The startup recovery will automatically pick up the reset segments and synthesize them using the optimized VoxCPM2 settings.")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == '__main__':
    main()
