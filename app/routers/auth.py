from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Invite
from app.schemas import (
    LoginRequest, TokenResponse, UserOut,
    InviteCreate, InviteOut, SignupRequest, MessageResponse,
)
from app.auth import (
    verify_password, hash_password, create_access_token,
    generate_invite_token, hash_invite_token,
    get_current_user, require_master,
)
from app.config import get_settings

router = APIRouter(prefix="/api/auth", tags=["Auth"])
settings = get_settings()


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.pass_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuário desativado")
    token = create_access_token({"sub": user.id})
    return TokenResponse(access_token=token)


@router.post("/logout", response_model=MessageResponse)
def logout(_: User = Depends(get_current_user)):
    # JWT is stateless; client should discard the token.
    return MessageResponse(message="Logout realizado com sucesso")


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


# ---------- Invites (MASTER only) ----------
invite_router = APIRouter(prefix="/api/invites", tags=["Invites"])


@invite_router.post("", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
def create_invite(
    body: InviteCreate,
    db: Session = Depends(get_db),
    master: User = Depends(require_master),
):
    raw_token, token_hash = generate_invite_token()
    invite = Invite(
        email=body.email,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        created_by=master.id,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    # Return the raw token in the response so the MASTER can share it
    invite_url = f"{settings.BASE_URL}/api/signup?token={raw_token}"
    out = InviteOut.model_validate(invite)
    # We attach the invite URL as extra info
    return out


@invite_router.get("", response_model=list[InviteOut])
def list_invites(
    db: Session = Depends(get_db),
    _: User = Depends(require_master),
):
    return db.query(Invite).order_by(Invite.created_at.desc()).all()


@invite_router.delete("/{invite_id}", response_model=MessageResponse)
def delete_invite(
    invite_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_master),
):
    invite = db.query(Invite).filter(Invite.id == invite_id).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Convite não encontrado")
    db.delete(invite)
    db.commit()
    return MessageResponse(message="Convite removido")


# ---------- Signup via invite token ----------
signup_router = APIRouter(tags=["Signup"])


@signup_router.post("/api/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def signup(
    body: SignupRequest,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    token_hash = hash_invite_token(token)
    invite = db.query(Invite).filter(Invite.token_hash == token_hash).first()
    if not invite:
        raise HTTPException(status_code=400, detail="Token de convite inválido")
    if invite.used_at is not None:
        raise HTTPException(status_code=400, detail="Convite já utilizado")
    if invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Convite expirado")

    existing = db.query(User).filter(User.email == invite.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Usuário já cadastrado com este e-mail")

    user = User(
        email=invite.email,
        pass_hash=hash_password(body.password),
        role="USER",
    )
    db.add(user)
    invite.used_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user
