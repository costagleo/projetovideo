from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


# ---------- Auth ----------
class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: str
    email: str
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Invites ----------
class InviteCreate(BaseModel):
    name: str


class InviteOut(BaseModel):
    id: str
    name: str
    expires_at: datetime
    used_at: Optional[datetime] = None
    created_at: datetime
    invite_url: Optional[str] = None

    class Config:
        from_attributes = True


class SignupRequest(BaseModel):
    email: str
    password: str


# ---------- Sections ----------
class SectionOut(BaseModel):
    id: str
    is_current: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Projects ----------
class ProjectCreate(BaseModel):
    name: str
    format: str = "landscape"  # landscape | vertical
    fit_mode: str = "smart_background"
    fps: int = 30
    transition_s: float = 0.5
    preset: str = "balanced"


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    format: Optional[str] = None
    fit_mode: Optional[str] = None
    fps: Optional[int] = None
    transition_s: Optional[float] = None
    preset: Optional[str] = None


class ProjectOut(BaseModel):
    id: str
    section_id: str
    name: str
    format: str
    fit_mode: str
    fps: int
    transition_s: float
    preset: str
    created_by: str
    created_at: datetime
    tracks: list["TrackOut"] = []

    class Config:
        from_attributes = True


# ---------- Tracks ----------
class TrackOut(BaseModel):
    id: str
    project_id: str
    audio_path: Optional[str] = None
    audio_filename: Optional[str] = None
    duration_ms: Optional[int] = None
    order_index: int
    images: list["ImageOut"] = []

    class Config:
        from_attributes = True


# ---------- Images ----------
class ImageOut(BaseModel):
    id: str
    track_id: str
    path: str
    order_index: int

    class Config:
        from_attributes = True


class ImageReorder(BaseModel):
    image_id: str
    order_index: int


class ImageReorderRequest(BaseModel):
    images: list[ImageReorder]


# ---------- Jobs ----------
class JobOut(BaseModel):
    id: str
    section_id: str
    project_id: str
    status: str
    progress: float
    eta_s: Optional[float] = None
    log_path: Optional[str] = None
    created_by: str
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_msg: Optional[str] = None

    class Config:
        from_attributes = True


# ---------- Generic ----------
class MessageResponse(BaseModel):
    message: str
