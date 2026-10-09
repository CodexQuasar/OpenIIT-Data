# Authentication and Authorization Dependencies
from typing import Optional
from datetime import datetime
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.auth.jwt_handler import verify_token, TokenData
from app.auth.rbac import Role, Permission, require_permission, require_role
from app.auth.models import UserModel, UserSessionModel
from data.database import get_db

# Security scheme
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> UserModel:
    """Get current authenticated user from JWT token."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_data: Optional[TokenData] = verify_token(credentials.credentials)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify session is still valid
    session = (
        db.query(UserSessionModel)
        .filter(UserSessionModel.id == token_data.session_id)
        .first()
    )
    if not session or session.revoked or session.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session revoked or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = (
        db.query(UserModel)
        .filter(UserModel.id == token_data.user_id)
        .first()
    )
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Attach session info for later use
    user.current_session = session  # type: ignore[attr-defined]
    return user


async def get_current_active_user(
    current_user: UserModel = Depends(get_current_user),
) -> UserModel:
    """Get current active user (alias for clarity)."""
    return current_user


# Role-based dependencies
def require_admin(current_user: UserModel = Depends(get_current_active_user)) -> UserModel:
    return require_role(current_user, Role.ADMIN)


def require_lender(current_user: UserModel = Depends(get_current_active_user)) -> UserModel:
    return require_role(current_user, Role.LENDER)


def require_field_agent(current_user: UserModel = Depends(get_current_active_user)) -> UserModel:
    return require_role(current_user, Role.FIELD_AGENT)


def require_auditor(current_user: UserModel = Depends(get_current_active_user)) -> UserModel:
    return require_role(current_user, Role.AUDITOR)


# Permission-based dependencies
def require_account_read(current_user: UserModel = Depends(get_current_active_user)) -> UserModel:
    return require_permission(current_user, Permission.ACCOUNT_READ)


def require_account_write(current_user: UserModel = Depends(get_current_active_user)) -> UserModel:
    return require_permission(current_user, Permission.ACCOUNT_WRITE)


def require_visit_create(current_user: UserModel = Depends(get_current_active_user)) -> UserModel:
    return require_permission(current_user, Permission.VISIT_CREATE)


def require_visit_read(current_user: UserModel = Depends(get_current_active_user)) -> UserModel:
    return require_permission(current_user, Permission.VISIT_READ)


def require_metrics_read(current_user: UserModel = Depends(get_current_active_user)) -> UserModel:
    return require_permission(current_user, Permission.METRICS_READ)


def require_user_management(current_user: UserModel = Depends(get_current_active_user)) -> UserModel:
    return require_permission(current_user, Permission.USER_MANAGE)


def require_system_config(current_user: UserModel = Depends(get_current_active_user)) -> UserModel:
    return require_permission(current_user, Permission.SYSTEM_CONFIG)


def require_audit_read(current_user: UserModel = Depends(get_current_active_user)) -> UserModel:
    return require_permission(current_user, Permission.AUDIT_READ)


def require_consent_manage(current_user: UserModel = Depends(get_current_active_user)) -> UserModel:
    return require_permission(current_user, Permission.CONSENT_MANAGE)


# Optional user (for endpoints that work with or without auth)
async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[UserModel]:
    """Get current user if authenticated, otherwise None."""
    if not credentials:
        return None

    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


async def require_operational_user(
    current_user: Optional[UserModel] = Depends(get_optional_user),
) -> Optional[UserModel]:
    """Require authentication for operational data outside test fixtures."""
    import os
    if os.environ.get("TESTING") == "1":
        return current_user
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user
