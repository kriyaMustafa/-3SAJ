import os
import sys

# Add backend directory to path
sys.path.append(os.path.abspath('backend'))

from database import SessionLocal
import models
from tasks import task_composite_and_export

def main():
    project_id = '4040d278-8aa9-4df0-b7be-d6c27e68b93e'
    print(f"Connecting to database to locate project {project_id}...")
    db = SessionLocal()
    try:
        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if not project:
            print("Project not found in database.")
            return
        
        print(f"Found project: '{project.name}' (current status: {project.status})")
        print("Resetting project status to pending and calling task_composite_and_export synchronously...")
        project.status = 'pending'
        db.commit()
        
        res = task_composite_and_export(project_id)
        print(f"Export task finished. Result: {res}")
        
    except Exception as e:
        import traceback
        print(f"An error occurred: {e}")
        traceback.print_exc()
    finally:
        db.close()

if __name__ == '__main__':
    main()
