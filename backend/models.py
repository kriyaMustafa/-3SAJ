import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from database import Base

class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    input_type = Column(String, nullable=False)  # 'local' or 'url'
    input_source = Column(String, nullable=False)
    source_language = Column(String, default="en")
    target_language = Column(String, default="km")
    genre_mode = Column(String, default="anime_recap")  # 'anime_recap' or 'drama_recap'
    generate_shorts = Column(Boolean, default=False)
    status = Column(String, default="pending")  # pending, ingesting, stemming, transcribing, translating, synthesizing, exporting, completed, failed
    video_path = Column(String, nullable=True)
    bgm_path = Column(String, nullable=True)
    vocals_path = Column(String, nullable=True)
    output_video_16_9 = Column(String, nullable=True)
    output_video_9_16 = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    chunks = relationship("VideoChunk", back_populates="project", cascade="all, delete-orphan")
    segments = relationship("Segment", back_populates="project", cascade="all, delete-orphan")
    thumbnails = relationship("Thumbnail", back_populates="project", cascade="all, delete-orphan")

class VideoChunk(Base):
    __tablename__ = "video_chunks"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    chunk_video_path = Column(String, nullable=True)
    chunk_audio_path = Column(String, nullable=True)
    vocals_path = Column(String, nullable=True)
    bgm_path = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending, stemming, transcribing, completed, failed
    error_traceback = Column(Text, nullable=True)

    project = relationship("Project", back_populates="chunks")

class Segment(Base):
    __tablename__ = "segments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    segment_index = Column(Integer, nullable=False)
    speaker_id = Column(String, default="Speaker 0")
    start_time = Column(Float, nullable=False)  # Seconds from absolute start of video
    end_time = Column(Float, nullable=False)    # Seconds from absolute start of video
    original_text = Column(Text, nullable=False)
    translated_text = Column(Text, nullable=True)
    audio_path = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending, translated, synthesized, failed
    error_traceback = Column(Text, nullable=True)

    project = relationship("Project", back_populates="segments")

class Thumbnail(Base):
    __tablename__ = "thumbnails"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    path = Column(String, nullable=False)
    score = Column(Float, default=0.0)
    timestamp = Column(Float, nullable=False)

    project = relationship("Project", back_populates="thumbnails")
