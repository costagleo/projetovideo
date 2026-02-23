import os

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Section, User
from app.schemas import SectionOut
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
        os.makedirs(os.path.join(settings.CURRENT_SECTION_PATH, "projects"), exist_ok=True)
    return section


@router.get("/current", response_model=SectionOut)
def get_current_section(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    section = _ensure_current_section(db)
    return section
