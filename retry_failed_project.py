import os
import sys
import time

# Add backend directory to path
sys.path.append(os.path.abspath('backend'))

from database import SessionLocal
import models
from tasks import task_demucs_separation

def main():
    project_id = '4040d278-8aa9-4df0-b7be-d6c27e68b93e'
    print(f"Connecting to database to locate project {project_id}...")
    db = SessionLocal()
    try:
        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if not project:
            print("Project not found in pipeline.db database.")
            return
        
        print(f"Found project: '{project.name}' (status: {project.status})")
        audio_path = os.path.join('data', project_id, 'source_audio.wav')
        if not os.path.exists(audio_path):
            print(f"Error: Source audio path not found at {audio_path}")
            return
            
        print("Resetting project status to pending and starting separation task...")
        project.status = 'pending'
        db.commit()
        
        # Trigger Demucs separation task
        # This will run synchronously in the main thread for the first stage (stemming)
        task_demucs_separation(project_id, audio_path)
        
        # Wait and monitor progress as subsequent tasks execute in the fallback thread pool
        print("Monitoring project progress...")
        while True:
            time.sleep(10)
            db.refresh(project)
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Status: {project.status}")
            if project.status in ['completed', 'failed', 'cancelled']:
                print(f"Pipeline finished with status: {project.status}")
                break
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        db.close()

if __name__ == '__main__':
    main()
