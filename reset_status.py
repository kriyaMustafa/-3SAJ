import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add backend to path
sys.path.append(os.path.abspath('backend'))

from database import engine
from models import Project

Session = sessionmaker(bind=engine)
session = Session()

project = session.query(Project).filter(Project.id == '27299abd-a243-46f9-895b-eb4c11dcb130').first()
if project:
    project.status = 'synthesizing'
    session.commit()
    print("Project status reset to synthesizing")
else:
    print("Project not found")

session.close()
