import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

# Database URL defaults to local SQLite file
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/pipeline.db")

# Automatically create the parent directory for SQLite files to prevent "unable to open database file" operational errors.
if DATABASE_URL.startswith("sqlite"):
    prefix = "sqlite:///"
    if DATABASE_URL.startswith(prefix):
        db_file_path = DATABASE_URL[len(prefix):]
        # Ignore in-memory SQLite databases
        if db_file_path and db_file_path != ":memory:":
            db_dir = os.path.dirname(db_file_path)
            if db_dir:
                try:
                    os.makedirs(db_dir, exist_ok=True)
                except Exception as dir_err:
                    print(f"[Database Warning] Could not create database directory '{db_dir}': {dir_err}")

from sqlalchemy import event

# For SQLite, use NullPool to disable connection pooling entirely. 
# This prevents QueuePool limit / exhaustion errors in concurrent thread pools.
engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine_kwargs["poolclass"] = NullPool
else:
    # Use robust defaults for server-based databases (e.g., PostgreSQL)
    engine_kwargs["pool_size"] = 20
    engine_kwargs["max_overflow"] = 50

engine = create_engine(DATABASE_URL, **engine_kwargs)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
