import os
import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project, Section, Job, User
from app.schemas import MessageResponse
from app.auth import get_current_user
from app.config import get_settings

router = APIRouter(tags=["Downloads"])
settings = get_settings()


def _get_output_files(project_id: str) -> list[dict]:
    """List all output files for a project."""
    output_dir = os.path.join(settings.CURRENT_SECTION_PATH, "projects", project_id, "output")
    if not os.path.exists(output_dir):
        return []
    files = []
    for fname in os.listdir(output_dir):
        fpath = os.path.join(output_dir, fname)
        if os.path.isfile(fpath):
            files.append({"name": fname, "path": fpath, "size": os.path.getsize(fpath)})
    return files


@router.get("/api/projects/{project_id}/outputs")
def list_outputs(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == project_id, Project.created_by == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    # Only show outputs if the latest job for this project completed successfully
    latest_job = (
        db.query(Job)
        .filter(Job.project_id == project_id)
        .order_by(Job.created_at.desc())
        .first()
    )
    if not latest_job or latest_job.status != "done":
        return []

    return _get_output_files(project_id)


@router.get("/api/outputs/{project_id}/{filename}/download")
def download_output(
    project_id: str,
    filename: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == project_id, Project.created_by == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    # Verify the latest job is done before allowing download
    latest_job = (
        db.query(Job)
        .filter(Job.project_id == project_id)
        .order_by(Job.created_at.desc())
        .first()
    )
    if not latest_job or latest_job.status != "done":
        raise HTTPException(status_code=400, detail="Renderização ainda não concluída")

    filepath = os.path.join(
        settings.CURRENT_SECTION_PATH, "projects", project_id, "output", filename
    )
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    return FileResponse(filepath, filename=filename, media_type="application/octet-stream")


@router.get("/api/section/outputs.zip")
def download_all_zip(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    section = db.query(Section).filter(Section.is_current == True).first()  # noqa: E712
    if not section:
        raise HTTPException(status_code=400, detail="Nenhuma seção ativa")

    projects = db.query(Project).filter(Project.section_id == section.id, Project.created_by == current_user.id).all()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for project in projects:
            files = _get_output_files(project.id)
            for f in files:
                arcname = f"{project.name}/{f['name']}"
                zf.write(f["path"], arcname)

    buf.seek(0)
    if buf.getbuffer().nbytes == 22:  # empty zip
        raise HTTPException(status_code=404, detail="Nenhum output disponível para download")

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=outputs.zip"},
    )
