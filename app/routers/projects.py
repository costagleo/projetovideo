import os
import shutil

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Section, Project, Track, User
from app.schemas import ProjectCreate, ProjectOut, MessageResponse
from app.auth import get_current_user
from app.config import get_settings

router = APIRouter(prefix="/api/projects", tags=["Projects"])
settings = get_settings()


def _get_current_section(db: Session) -> Section:
    section = db.query(Section).filter(Section.is_current == True).first()  # noqa: E712
    if not section:
        raise HTTPException(status_code=400, detail="Nenhuma seção ativa. Crie uma nova seção primeiro.")
    return section


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    section = _get_current_section(db)

    project = Project(
        section_id=section.id,
        name=body.name,
        format=body.format,
        fit_mode=body.fit_mode,
        fps=body.fps,
        transition_s=body.transition_s,
        preset=body.preset,
        created_by=current_user.id,
    )
    db.add(project)
    db.flush()

    # Create a default track (single music mode)
    track = Track(project_id=project.id, order_index=0)
    db.add(track)

    db.commit()
    db.refresh(project)

    # Create directory structure
    project_dir = os.path.join(settings.CURRENT_SECTION_PATH, "projects", project.id)
    os.makedirs(os.path.join(project_dir, "input"), exist_ok=True)
    os.makedirs(os.path.join(project_dir, "output"), exist_ok=True)
    os.makedirs(os.path.join(project_dir, "logs"), exist_ok=True)

    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    section = _get_current_section(db)
    return (
        db.query(Project)
        .options(joinedload(Project.tracks).joinedload(Track.images))
        .filter(Project.section_id == section.id)
        .order_by(Project.created_at)
        .all()
    )


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    project = (
        db.query(Project)
        .options(joinedload(Project.tracks).joinedload(Track.images))
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    return project


@router.delete("/{project_id}", response_model=MessageResponse)
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    # Delete files
    project_dir = os.path.join(settings.CURRENT_SECTION_PATH, "projects", project.id)
    if os.path.exists(project_dir):
        shutil.rmtree(project_dir)

    db.delete(project)
    db.commit()
    return MessageResponse(message="Projeto removido")
