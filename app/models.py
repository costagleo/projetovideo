import datetime
import uuid

from sqlalchemy import (
    Column, String, Integer, Boolean, Float, Text,
    DateTime, ForeignKey, Enum as SAEnum,
)
from sqlalchemy.orm import relationship

from app.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# ---------- Users ----------
class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    pass_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="USER")  # MASTER | USER
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)

    projects = relationship("Project", back_populates="creator")
    jobs = relationship("Job", back_populates="creator")


# ---------- Invites ----------
class Invite(Base):
    __tablename__ = "invites"

    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, nullable=False)
    token_hash = Column(String, nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)


# ---------- Sections ----------
class Section(Base):
    __tablename__ = "sections"

    id = Column(String, primary_key=True, default=generate_uuid)
    is_current = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)

    projects = relationship("Project", back_populates="section", cascade="all, delete-orphan")
    jobs = relationship("Job", back_populates="section", cascade="all, delete-orphan")


# ---------- Projects ----------
class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=generate_uuid)
    section_id = Column(String, ForeignKey("sections.id"), nullable=False)
    name = Column(String, nullable=False)
    format = Column(String, nullable=False, default="landscape")  # landscape | vertical
    fit_mode = Column(String, nullable=False, default="smart_background")
    fps = Column(Integer, default=30)
    transition_s = Column(Float, default=0.5)
    preset = Column(String, default="balanced")
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utcnow)

    section = relationship("Section", back_populates="projects")
    creator = relationship("User", back_populates="projects")
    tracks = relationship("Track", back_populates="project", cascade="all, delete-orphan")
    jobs = relationship("Job", back_populates="project", cascade="all, delete-orphan")


# ---------- Tracks ----------
class Track(Base):
    __tablename__ = "tracks"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    audio_path = Column(String, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    order_index = Column(Integer, default=0)

    project = relationship("Project", back_populates="tracks")
    images = relationship("Image", back_populates="track", cascade="all, delete-orphan")


# ---------- Images ----------
class Image(Base):
    __tablename__ = "images"

    id = Column(String, primary_key=True, default=generate_uuid)
    track_id = Column(String, ForeignKey("tracks.id"), nullable=False)
    path = Column(String, nullable=False)
    order_index = Column(Integer, default=0)

    track = relationship("Track", back_populates="images")


# ---------- Jobs ----------
class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=generate_uuid)
    section_id = Column(String, ForeignKey("sections.id"), nullable=False)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    status = Column(String, nullable=False, default="queued")  # queued | running | done | error
    progress = Column(Float, default=0.0)
    eta_s = Column(Float, nullable=True)
    log_path = Column(String, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error_msg = Column(Text, nullable=True)

    section = relationship("Section", back_populates="jobs")
    project = relationship("Project", back_populates="jobs")
    creator = relationship("User", back_populates="jobs")
