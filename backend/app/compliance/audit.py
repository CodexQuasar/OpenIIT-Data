# Audit logging module for regulatory compliance
# Records who did what, when, and why - for RBI/DPDP audit trails.
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from dataclasses import dataclass
import uuid
import json

from sqlalchemy.orm import Session
from sqlalchemy import Column, String, DateTime, Text, Index, JSON

from data.models import Base


class AuditAction(str, Enum):
    """Actions that must be audited."""
    # Auth
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    LOGIN_FAILED = "LOGIN_FAILED"
    TOKEN_REFRESH = "TOKEN_REFRESH"
    PASSWORD_RESET = "PASSWORD_RESET"

    # Data access
    ACCOUNT_READ = "ACCOUNT_READ"
    ACCOUNT_WRITE = "ACCOUNT_WRITE"
    ACCOUNT_DELETE = "ACCOUNT_DELETE"
    VISIT_CREATE = "VISIT_CREATE"
    VISIT_READ = "VISIT_READ"
    VISIT_UPDATE = "VISIT_UPDATE"
    PREDICTION_READ = "PREDICTION_READ"
    PREDICTION_WRITE = "PREDICTION_WRITE"
    EXPORT_DATA = "EXPORT_DATA"

    # Consent (DPDP)
    CONSENT_GRANTED = "CONSENT_GRANTED"
    CONSENT_WITHDRAWN = "CONSENT_WITHDRAWN"
    CONSENT_CHECKED = "CONSENT_CHECKED"
    DATA_ACCESS_REQUEST = "DATA_ACCESS_REQUEST"
    DATA_CORRECTION_REQUEST = "DATA_CORRECTION_REQUEST"
    DATA_ERASURE_REQUEST = "DATA_ERASURE_REQUEST"

    # Contact (RBI)
    CONTACT_ATTEMPT = "CONTACT_ATTEMPT"
    CONTACT_BLOCKED = "CONTACT_BLOCKED"

    # System
    CONFIG_CHANGE = "CONFIG_CHANGE"
    MODEL_UPDATE = "MODEL_UPDATE"
    DATA_RETENTION_PURGE = "DATA_RETENTION_PURGE"
    BACKGROUND_TASK = "BACKGROUND_TASK"


class AuditLogModel(Base):
    """Immutable audit log entry."""
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True)
    timestamp = Column(DateTime, nullable=False, index=True, default=datetime.utcnow)
    actor_id = Column(String, nullable=True, index=True)
    actor_role = Column(String, nullable=True)
    action = Column(String, nullable=False, index=True)
    resource_type = Column(String, nullable=True)
    resource_id = Column(String, nullable=True, index=True)
    details = Column(JSON, nullable=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    outcome = Column(String, nullable=True)  # SUCCESS / FAILURE / DENIED
    request_id = Column(String, nullable=True, index=True)

    __table_args__ = (
        Index("ix_audit_actor_time", "actor_id", "timestamp"),
        Index("ix_audit_action_time", "action", "timestamp"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
    )


@dataclass
class AuditEntry:
    """Structured audit entry."""
    action: AuditAction
    actor_id: Optional[str] = None
    actor_role: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    outcome: str = "SUCCESS"
    request_id: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "actor_id": self.actor_id,
            "actor_role": self.actor_role,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": self.details,
            "outcome": self.outcome,
        }


class AuditLogger:
    """Writes audit entries to the database."""

    def __init__(self, db: Session):
        self.db = db

    def log(self, entry: AuditEntry) -> str:
        """Persist an audit entry. Returns the log ID."""
        log_id = f"aud_{uuid.uuid4().hex[:14]}"
        model = AuditLogModel(
            id=log_id,
            timestamp=datetime.utcnow(),
            actor_id=entry.actor_id,
            actor_role=entry.actor_role,
            action=entry.action.value,
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            details=entry.details,
            ip_address=entry.ip_address,
            user_agent=entry.user_agent,
            outcome=entry.outcome,
            request_id=entry.request_id,
        )
        self.db.add(model)
        self.db.commit()
        return log_id

    def log_auth(
        self,
        action: AuditAction,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        outcome: str = "SUCCESS",
        details: Optional[Dict] = None,
    ) -> str:
        return self.log(AuditEntry(
            action=action,
            actor_id=user_id,
            ip_address=ip_address,
            outcome=outcome,
            details=details,
        ))

    def log_data_access(
        self,
        action: AuditAction,
        actor_id: str,
        resource_type: str,
        resource_id: str,
        outcome: str = "SUCCESS",
        details: Optional[Dict] = None,
        ip_address: Optional[str] = None,
    ) -> str:
        return self.log(AuditEntry(
            action=action,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            details=details,
            ip_address=ip_address,
        ))

    def log_consent(
        self,
        action: AuditAction,
        user_id: str,
        consent_id: Optional[str] = None,
        details: Optional[Dict] = None,
    ) -> str:
        return self.log(AuditEntry(
            action=action,
            actor_id=user_id,
            resource_type="consent",
            resource_id=consent_id,
            details=details,
        ))

    def log_contact(
        self,
        account_id: str,
        allowed: bool,
        actor_id: Optional[str] = None,
        details: Optional[Dict] = None,
    ) -> str:
        return self.log(AuditEntry(
            action=AuditAction.CONTACT_ATTEMPT if allowed else AuditAction.CONTACT_BLOCKED,
            actor_id=actor_id,
            resource_type="account",
            resource_id=account_id,
            outcome="SUCCESS" if allowed else "DENIED",
            details=details,
        ))

    # -- Query helpers ------------------------------------------------------
    def get_by_actor(
        self,
        actor_id: str,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[AuditLogModel]:
        q = self.db.query(AuditLogModel).filter(AuditLogModel.actor_id == actor_id)
        if since:
            q = q.filter(AuditLogModel.timestamp >= since)
        return q.order_by(AuditLogModel.timestamp.desc()).limit(limit).all()

    def get_by_resource(
        self,
        resource_type: str,
        resource_id: str,
        limit: int = 100,
    ) -> List[AuditLogModel]:
        return (
            self.db.query(AuditLogModel)
            .filter(
                AuditLogModel.resource_type == resource_type,
                AuditLogModel.resource_id == resource_id,
            )
            .order_by(AuditLogModel.timestamp.desc())
            .limit(limit)
            .all()
        )

    def get_by_action(
        self,
        action: AuditAction,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[AuditLogModel]:
        q = self.db.query(AuditLogModel).filter(AuditLogModel.action == action.value)
        if since:
            q = q.filter(AuditLogModel.timestamp >= since)
        return q.order_by(AuditLogModel.timestamp.desc()).limit(limit).all()

    def search(
        self,
        actor_id: Optional[str] = None,
        action: Optional[str] = None,
        resource_id: Optional[str] = None,
        outcome: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[AuditLogModel]:
        q = self.db.query(AuditLogModel)
        if actor_id:
            q = q.filter(AuditLogModel.actor_id == actor_id)
        if action:
            q = q.filter(AuditLogModel.action == action)
        if resource_id:
            q = q.filter(AuditLogModel.resource_id == resource_id)
        if outcome:
            q = q.filter(AuditLogModel.outcome == outcome)
        if since:
            q = q.filter(AuditLogModel.timestamp >= since)
        if until:
            q = q.filter(AuditLogModel.timestamp <= until)
        return q.order_by(AuditLogModel.timestamp.desc()).limit(limit).all()

    def count_violations(self, since: Optional[datetime] = None) -> Dict[str, int]:
        """Count denied/failed actions by type for compliance dashboards."""
        q = self.db.query(AuditLogModel).filter(
            AuditLogModel.outcome.in_(["FAILURE", "DENIED"])
        )
        if since:
            q = q.filter(AuditLogModel.timestamp >= since)
        rows = q.all()
        counts: Dict[str, int] = {}
        for r in rows:
            counts[r.action] = counts.get(r.action, 0) + 1
        return counts
