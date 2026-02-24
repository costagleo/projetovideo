import os
import subprocess

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project, Track, Image, User
from app.schemas import TrackOut, ImageOut, ImageReorderRequest, MessageResponse
from app.auth import get_current_user
from app.config import get_settings

router = APIRouter(tags=["Uploads"])
settings = get_settings()

ALLOWED_AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"}
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}


def _get_audio_duration_ms(path: str) -> int | None:
    """Use ffprobe to get audio duration in milliseconds."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                path,
            ],
            capture_output=True, text=True, timeout=10,
        )
        seconds = float(result.stdout.strip())
        return int(seconds * 1000)
    except Exception:
        return None


@router.post("/api/tracks/{track_id}/audio", response_model=TrackOut)
async def upload_audio(
    track_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    track = db.query(Track).filter(Track.id == track_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Track não encontrada")
    project = db.query(Project).filter(Project.id == track.project_id, Project.created_by == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_AUDIO_EXTS:
        raise HTTPException(status_code=400, detail=f"Formato de áudio não suportado: {ext}")

    project_dir = os.path.join(
        settings.CURRENT_SECTION_PATH, "projects", track.project_id, "input"
    )
    os.makedirs(project_dir, exist_ok=True)

    filename = f"audio_{track.order_index}{ext}"
    filepath = os.path.join(project_dir, filename)

    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    track.audio_path = filepath
    track.audio_filename = os.path.splitext(file.filename or "audio")[0]
    track.duration_ms = _get_audio_duration_ms(filepath)
    db.commit()
    db.refresh(track)
    return track


@router.post("/api/tracks/{track_id}/images", response_model=list[ImageOut])
async def upload_images(
    track_id: str,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    track = db.query(Track).filter(Track.id == track_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Track não encontrada")
    project = db.query(Project).filter(Project.id == track.project_id, Project.created_by == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    project_dir = os.path.join(
        settings.CURRENT_SECTION_PATH, "projects", track.project_id, "input"
    )
    os.makedirs(project_dir, exist_ok=True)

    # Get current max order_index
    max_idx = db.query(Image).filter(Image.track_id == track_id).count()
    created = []

    for i, file in enumerate(files):
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in ALLOWED_IMAGE_EXTS:
            continue  # Skip unsupported formats silently

        idx = max_idx + i
        filename = f"img_{track.order_index}_{idx}{ext}"
        filepath = os.path.join(project_dir, filename)

        content = await file.read()
        with open(filepath, "wb") as f:
            f.write(content)

        img = Image(track_id=track_id, path=filepath, order_index=idx)
        db.add(img)
        created.append(img)

    db.commit()
    for img in created:
        db.refresh(img)
    return created


@router.delete("/api/images/{image_id}", response_model=MessageResponse)
def delete_image(
    image_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    img = db.query(Image).filter(Image.id == image_id).first()
    if not img:
        raise HTTPException(status_code=404, detail="Imagem não encontrada")
    track = db.query(Track).filter(Track.id == img.track_id).first()
    if track:
        project = db.query(Project).filter(Project.id == track.project_id, Project.created_by == current_user.id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Projeto não encontrado")

    # Delete file from disk
    if img.path and os.path.exists(img.path):
        os.remove(img.path)

    db.delete(img)
    db.commit()
    return MessageResponse(message="Imagem removida")


@router.patch("/api/images/reorder", response_model=MessageResponse)
def reorder_images(
    body: ImageReorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    for item in body.images:
        img = db.query(Image).filter(Image.id == item.image_id).first()
        if img:
            img.order_index = item.order_index
    db.commit()
    return MessageResponse(message="Ordem atualizada")
