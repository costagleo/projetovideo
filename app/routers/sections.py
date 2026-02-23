import os
import shutil

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Section, User
from app.schemas import SectionOut, MessageResponse
from app.auth import get_current_user
from app.config import get_settings

router = APIRouter(prefix="/api/section", tags=["Sections"])
settings = get_settings()


def _ensure_current_section(db: Session) -> Section:
    """Return the current section, creating one if it doesn't exist."""
    section = db.query(Section).filter(Section.is_current == True).first()  # noqa: E712
    if not section:
        section = Section(is_current=True)
        db.add(section)
        db.commit()
        db.refresh(section)
        # Create directory structure
        os.makedirs(os.path.join(settings.CURRENT_SECTION_PATH, "projects"), exist_ok=True)
    return section


@router.get("/current", response_model=SectionOut)
def get_current_section(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    section = _ensure_current_section(db)
    return section


@router.post("/new", response_model=SectionOut)
def new_section(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    # 1. Delete the old section's files
    if os.path.exists(settings.CURRENT_SECTION_PATH):
        shutil.rmtree(settings.CURRENT_SECTION_PATH)

    # 2. Delete old section records (cascade deletes projects, tracks, images, jobs)
    old = db.query(Section).filter(Section.is_current == True).first()  # noqa: E712
    if old:
        db.delete(old)
        db.commit()

    # 3. Create a fresh section
    section = Section(is_current=True)
    db.add(section)
    db.commit()
    db.refresh(section)

    # 4. Recreate directory structure
    os.makedirs(os.path.join(settings.CURRENT_SECTION_PATH, "projects"), exist_ok=True)

    return section
