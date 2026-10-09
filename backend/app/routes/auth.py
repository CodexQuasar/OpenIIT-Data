# Authentication routes: register, login, logout, me
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4
import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from data.database import get_db
from app.auth.models import UserModel, UserSessionModel
from app.auth.jwt_handler import create_access_token, verify_token
from app.auth.dependencies import get_current_user, security
from app.auth.rbac import Role
from app.compliance.audit import AuditLogger, AuditEntry, AuditAction

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: str = Field(default="field_agent")
    tenant_id: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_hours: int
    user_id: str
    role: str
    tenant_id: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    username: str
    full_name: Optional[str]
    email: Optional[str]
    role: str
    tenant_id: Optional[str]
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime]


class SessionResponse(BaseModel):
    session_id: str
    revoked: bool
    expires_at: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return secrets.compare_digest(_hash_password(password, salt), stored)


VALID_ROLES = {r.value for r in Role}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(request: RegisterRequest, req: Request, db: Session = Depends(get_db)):
    """Register a new user (admin can create any role; first user is admin)."""
    if request.role not in VALID_ROLES:
        raise HTTPException(400, detail=f"Invalid role; must be one of {sorted(VALID_ROLES)}")

    existing = db.query(UserModel).filter(UserModel.username == request.username).first()
    if existing:
        raise HTTPException(409, detail="Username already taken")

    # First registered user becomes admin
    user_count = db.query(UserModel).count()
    role = "admin" if user_count == 0 else request.role

    user = UserModel(
        id=f"usr_{uuid4().hex[:12]}",
        username=request.username,
        email=request.email,
        full_name=request.full_name,
        hashed_password=_hash_password(request.password),
        role=role,
        tenant_id=request.tenant_id,
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    AuditLogger(db).log(AuditEntry(
        action=AuditAction.LOGIN,
        actor_id=user.id,
        actor_role=user.role,
        resource_type="user",
        resource_id=user.id,
        details={"event": "user_registered", "role": role},
        ip_address=req.client.host if req.client else None,
    ))

    return {"user_id": user.id, "username": user.username, "role": user.role}


@router.post("/auth/login", response_model=TokenResponse)
def login(request: LoginRequest, req: Request, db: Session = Depends(get_db)):
    """Authenticate and return a JWT access token + session."""
    user = db.query(UserModel).filter(UserModel.username == request.username).first()

    audit = AuditLogger(db)

    if not user or not user.is_active or not _verify_password(request.password, user.hashed_password):
        audit.log(AuditEntry(
            action=AuditAction.LOGIN_FAILED,
            actor_id=user.id if user else None,
            details={"username": request.username},
            outcome="FAILURE",
            ip_address=req.client.host if req.client else None,
        ))
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # Create session
    session = UserSessionModel(
        id=f"ses_{uuid4().hex[:14]}",
        user_id=user.id,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(hours=12),
        revoked=False,
        ip_address=req.client.host if req.client else None,
        user_agent=req.headers.get("user-agent"),
    )
    db.add(session)

    user.last_login_at = datetime.utcnow()
    db.commit()

    token = create_access_token(
        user_id=user.id,
        session_id=session.id,
        role=user.role,
        tenant_id=user.tenant_id,
    )

    audit.log(AuditEntry(
        action=AuditAction.LOGIN,
        actor_id=user.id,
        actor_role=user.role,
        resource_type="session",
        resource_id=session.id,
        ip_address=req.client.host if req.client else None,
    ))

    return TokenResponse(
        access_token=token,
        expires_in_hours=12,
        user_id=user.id,
        role=user.role,
        tenant_id=user.tenant_id,
    )


@router.post("/auth/logout")
def logout(
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke the current session."""
    session = getattr(user, "current_session", None)
    if session:
        session.revoked = True
        session.revoked_at = datetime.utcnow()
        db.commit()

    AuditLogger(db).log(AuditEntry(
        action=AuditAction.LOGOUT,
        actor_id=user.id,
        actor_role=user.role,
        resource_type="session",
        resource_id=session.id if session else None,
    ))
    return {"status": "logged_out"}


@router.get("/auth/me", response_model=UserResponse)
def me(user: UserModel = Depends(get_current_user)):
    """Return the current authenticated user's profile."""
    return UserResponse(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        tenant_id=user.tenant_id,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.post("/auth/refresh")
def refresh_token(
    credentials=Depends(security),
    db: Session = Depends(get_db),
):
    """Issue a new token from a still-valid one."""
    if not credentials:
        raise HTTPException(401, detail="Not authenticated")
    data = verify_token(credentials.credentials)
    if not data:
        raise HTTPException(401, detail="Invalid or expired token")

    session = db.query(UserSessionModel).filter(UserSessionModel.id == data.session_id).first()
    if not session or session.revoked or session.expires_at < datetime.utcnow():
        raise HTTPException(401, detail="Session revoked or expired")

    user = db.query(UserModel).filter(UserModel.id == data.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(401, detail="User not found or inactive")

    # Extend session
    session.expires_at = datetime.utcnow() + timedelta(hours=12)
    db.commit()

    token = create_access_token(
        user_id=user.id,
        session_id=session.id,
        role=user.role,
        tenant_id=user.tenant_id,
    )
    return TokenResponse(
        access_token=token,
        expires_in_hours=12,
        user_id=user.id,
        role=user.role,
        tenant_id=user.tenant_id,
    )
