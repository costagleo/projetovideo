import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.database import init_db, SessionLocal
from app.models import User, Section
from app.auth import hash_password


settings = get_settings()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
# Cache-busting version: changes on each server start
_static_version = str(int(time.time()))


def _ensure_master_user():
    """Create MASTER user on first run if it doesn't exist."""
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == settings.MASTER_EMAIL).first()
        if not existing:
            master = User(
                email=settings.MASTER_EMAIL,
                pass_hash=hash_password(settings.MASTER_PASSWORD),
                role="MASTER",
            )
            db.add(master)
            db.commit()
    finally:
        db.close()


def _ensure_current_section():
    """Ensure there is always a current section."""
    db = SessionLocal()
    try:
        section = db.query(Section).filter(Section.is_current == True).first()  # noqa: E712
        if not section:
            section = Section(is_current=True)
            db.add(section)
            db.commit()
            os.makedirs(os.path.join(settings.CURRENT_SECTION_PATH, "projects"), exist_ok=True)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    _ensure_master_user()
    _ensure_current_section()
    yield
    # Shutdown


app = FastAPI(
    title="Axidia Video Render API",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
from app.routers.auth import router as auth_router, invite_router, users_router, signup_router
from app.routers.sections import router as sections_router
from app.routers.projects import router as projects_router
from app.routers.uploads import router as uploads_router
from app.routers.jobs import router as jobs_router
from app.routers.downloads import router as downloads_router

app.include_router(auth_router)
app.include_router(invite_router)
app.include_router(users_router)
app.include_router(signup_router)
app.include_router(sections_router)
app.include_router(projects_router)
app.include_router(uploads_router)
app.include_router(jobs_router)
app.include_router(downloads_router)


# Mount static files
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")


# ---------- HTML routes ----------
@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request, "v": _static_version})


@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "v": _static_version})


@app.get("/signup")
def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request, "v": _static_version})


@app.get("/health")
def health():
    return {"status": "ok"}
