import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Job, Project, Section, Track, User
from app.schemas import JobOut, MessageResponse
from app.auth import get_current_user
from app.config import get_settings
from app.worker import enqueue_render, request_cancel

router = APIRouter(tags=["Jobs"])
settings = get_settings()


def _get_current_section(db: Session) -> Section:
    section = db.query(Section).filter(Section.is_current == True).first()  # noqa: E712
    if not section:
        raise HTTPException(status_code=400, detail="Nenhuma seção ativa")
    return section


@router.post("/api/projects/{project_id}/render", response_model=JobOut, status_code=201)
def render_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == project_id, Project.created_by == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    # Validate project has at least one track with audio and images
    tracks = db.query(Track).filter(Track.project_id == project_id).all()
    if not tracks:
        raise HTTPException(status_code=400, detail="Projeto não possui tracks")
    for t in tracks:
        if not t.audio_path:
            raise HTTPException(status_code=400, detail=f"Track {t.order_index} sem áudio")
        if not t.images:
            raise HTTPException(status_code=400, detail=f"Track {t.order_index} sem imagens")

    job = Job(
        section_id=project.section_id,
        project_id=project.id,
        created_by=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    enqueue_render(job.id)
    return job


@router.post("/api/section/render_all", response_model=list[JobOut], status_code=201)
def render_all(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    section = _get_current_section(db)
    projects = db.query(Project).filter(Project.section_id == section.id, Project.created_by == current_user.id).all()
    if not projects:
        raise HTTPException(status_code=400, detail="Nenhum projeto na seção atual")

    created_jobs = []
    for project in projects:
        tracks = db.query(Track).filter(Track.project_id == project.id).all()
        # Skip projects without valid tracks
        valid = all(t.audio_path and t.images for t in tracks) and len(tracks) > 0
        if not valid:
            continue

        job = Job(
            section_id=section.id,
            project_id=project.id,
            created_by=current_user.id,
        )
        db.add(job)
        db.flush()
        created_jobs.append(job)

    if not created_jobs:
        raise HTTPException(status_code=400, detail="Nenhum projeto válido para renderizar")

    db.commit()
    for j in created_jobs:
        db.refresh(j)
        enqueue_render(j.id)

    return created_jobs


@router.get("/api/jobs", response_model=list[JobOut])
def list_jobs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    section = _get_current_section(db)
    return (
        db.query(Job)
        .filter(Job.section_id == section.id, Job.created_by == current_user.id)
        .order_by(Job.created_at)
        .all()
    )


@router.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.query(Job).filter(Job.id == job_id, Job.created_by == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return job


@router.get("/api/jobs/{job_id}/log")
def get_job_log(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.query(Job).filter(Job.id == job_id, Job.created_by == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    if not job.log_path or not os.path.exists(job.log_path):
        return {"log": ""}
    with open(job.log_path, "r") as f:
        return {"log": f.read()}


@router.delete("/api/jobs/{job_id}", response_model=MessageResponse)
def delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.query(Job).filter(Job.id == job_id, Job.created_by == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")

    # Signal cancellation if the job is still active.
    # This sets a Redis flag that the render loop detects to kill FFmpeg,
    # and also cancels the RQ job if it's still queued.
    if job.status in ("queued", "running"):
        request_cancel(job.id)

    # Delete log file if exists
    if job.log_path and os.path.exists(job.log_path):
        try:
            os.remove(job.log_path)
        except OSError:
            pass

    db.delete(job)
    db.commit()
    return MessageResponse(message="Job removido")


@router.get("/api/jobs/{job_id}/download")
def download_job_output(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.query(Job).filter(Job.id == job_id, Job.created_by == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    if job.status != "done":
        raise HTTPException(status_code=400, detail="Renderização ainda não concluída")

    project = db.query(Project).filter(Project.id == job.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    output_dir = os.path.join(settings.CURRENT_SECTION_PATH, "projects", project.id, "output")
    if not os.path.exists(output_dir):
        raise HTTPException(status_code=404, detail="Nenhum arquivo de saída encontrado")

    # Find the output file (single continuous video)
    files = [f for f in os.listdir(output_dir) if f.endswith(".mp4")]
    if not files:
        raise HTTPException(status_code=404, detail="Nenhum vídeo encontrado")

    filepath = os.path.join(output_dir, files[0])
    return FileResponse(filepath, filename=files[0], media_type="application/octet-stream")
