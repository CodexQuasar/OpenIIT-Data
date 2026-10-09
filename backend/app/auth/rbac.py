# Role-Based Access Control (RBAC) definitions and helpers
from enum import Enum
from typing import Set, List

from fastapi import HTTPException, status


class Role(str, Enum):
    """Application roles."""
    ADMIN = "admin"
    LENDER = "lender"
    FIELD_AGENT = "field_agent"
    AUDITOR = "auditor"
    SUPERVISOR = "supervisor"


class Permission(str, Enum):
    """Granular permissions."""
    ACCOUNT_READ = "account:read"
    ACCOUNT_WRITE = "account:write"
    ACCOUNT_DELETE = "account:delete"
    VISIT_CREATE = "visit:create"
    VISIT_READ = "visit:read"
    VISIT_UPDATE = "visit:update"
    PREDICTION_READ = "prediction:read"
    PREDICTION_WRITE = "prediction:write"
    METRICS_READ = "metrics:read"
    EXPORT_DATA = "data:export"
    USER_MANAGE = "user:manage"
    SYSTEM_CONFIG = "system:config"
    CONSENT_MANAGE = "consent:manage"
    AUDIT_READ = "audit:read"
    CONTACT_INITIATE = "contact:initiate"


# Role -> permissions mapping
ROLE_PERMISSIONS: dict[Role, Set[Permission]] = {
    Role.ADMIN: {
        Permission.ACCOUNT_READ, Permission.ACCOUNT_WRITE, Permission.ACCOUNT_DELETE,
        Permission.VISIT_CREATE, Permission.VISIT_READ, Permission.VISIT_UPDATE,
        Permission.PREDICTION_READ, Permission.PREDICTION_WRITE,
        Permission.METRICS_READ, Permission.EXPORT_DATA,
        Permission.USER_MANAGE, Permission.SYSTEM_CONFIG,
        Permission.CONSENT_MANAGE, Permission.AUDIT_READ,
        Permission.CONTACT_INITIATE,
    },
    Role.LENDER: {
        Permission.ACCOUNT_READ, Permission.ACCOUNT_WRITE,
        Permission.VISIT_READ,
        Permission.PREDICTION_READ,
        Permission.METRICS_READ, Permission.EXPORT_DATA,
        Permission.CONSENT_MANAGE, Permission.AUDIT_READ,
        Permission.CONTACT_INITIATE,
    },
    Role.SUPERVISOR: {
        Permission.ACCOUNT_READ,
        Permission.VISIT_CREATE, Permission.VISIT_READ, Permission.VISIT_UPDATE,
        Permission.PREDICTION_READ,
        Permission.METRICS_READ,
        Permission.CONTACT_INITIATE,
    },
    Role.FIELD_AGENT: {
        Permission.ACCOUNT_READ,
        Permission.VISIT_CREATE, Permission.VISIT_READ,
        Permission.PREDICTION_READ,
        Permission.CONTACT_INITIATE,
    },
    Role.AUDITOR: {
        Permission.ACCOUNT_READ,
        Permission.VISIT_READ,
        Permission.PREDICTION_READ,
        Permission.METRICS_READ,
        Permission.AUDIT_READ,
    },
}


def get_permissions(role: str) -> Set[Permission]:
    """Get the permission set for a role (empty set for unknown roles)."""
    try:
        return ROLE_PERMISSIONS.get(Role(role), set())
    except ValueError:
        return set()


def has_permission(role: str, permission: Permission) -> bool:
    """Check whether a role has a permission."""
    return permission in get_permissions(role)


def require_role(user, role: Role) -> type:
    """Raise 403 unless the user has the required role (or is admin)."""
    user_role = getattr(user, "role", None)
    if user_role == Role.ADMIN.value or user_role == role.value:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Role '{user_role}' is not permitted; requires '{role.value}'",
    )


def require_permission(user, permission: Permission) -> type:
    """Raise 403 unless the user's role includes the permission."""
    user_role = getattr(user, "role", None)
    if not has_permission(user_role, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {permission.value}",
        )
    return user


def require_any_permission(user, permissions: List[Permission]) -> type:
    """Raise 403 unless the user has at least one of the permissions."""
    user_role = getattr(user, "role", None)
    role_perms = get_permissions(user_role)
    if not any(p in role_perms for p in permissions):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing one of: {[p.value for p in permissions]}",
        )
    return user
