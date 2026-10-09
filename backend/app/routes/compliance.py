# Compliance routes: DPDP consent, RBI contact rules, audit log queries
from datetime import datetime, date
from typing import Optional, List
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from data.database import get_db
from app.auth.dependencies import get_current_user, require_audit_read, require_consent_manage
from app.auth.models import UserModel
from app.compliance.dpdp import (
    DPDPConsentManager, DataCategory, ProcessingPurpose,
    ConsentStatus, RetentionPolicy, DataSubjectRights,
)
from app.compliance.rbi_contact import (
    RBIContactEnforcer, ContactChannel, ContactOutcome, ContactLogModel,
)
from app.compliance.audit import AuditLogger, AuditEntry, AuditAction

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ConsentGrantRequest(BaseModel):
    data_categories: List[str]
    purposes: List[str]
    consent_text: str
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=3650)


class ConsentResponse(BaseModel):
    consent_id: str
    user_id: str
    data_categories: List[str]
    purposes: List[str]
    status: str
    granted_at: Optional[str]
    withdrawn_at: Optional[str]
    expires_at: Optional[str]
    consent_text: str


class ContactCheckRequest(BaseModel):
    account_id: str
    channel: str = "PHONE_CALL"
    do_not_contact: bool = False
    borrower_consented_outside_window: bool = False
    is_legal_notice: bool = False


class ContactCheckResponse(BaseModel):
    allowed: bool
    violations: List[dict]
    reason: Optional[str]
    attempts_today: int
    attempts_this_week: int
    next_allowed_at: Optional[str]


class ContactRecordRequest(BaseModel):
    account_id: str
    channel: str = "PHONE_CALL"
    outcome: str = "NOT_REACHED"
    notes: Optional[str] = None
    do_not_contact: bool = False
    is_legal_notice: bool = False


class RetentionCheckResponse(BaseModel):
    category: str
    purpose: str
    retention_days: int
    expiry_date: Optional[str]


class DataSubjectAccessResponse(BaseModel):
    personal_data: dict
    processing_purposes: List[str]
    data_categories: List[str]
    retention_periods: dict
    source: str


class AuditLogResponse(BaseModel):
    id: str
    timestamp: str
    actor_id: Optional[str]
    actor_role: Optional[str]
    action: str
    resource_type: Optional[str]
    resource_id: Optional[str]
    outcome: Optional[str]
    details: Optional[dict]


# ---------------------------------------------------------------------------
# DPDP Consent endpoints
# ---------------------------------------------------------------------------
@router.post("/compliance/consent", response_model=ConsentResponse, status_code=201)
def grant_consent(
    request: ConsentGrantRequest,
    req: Request,
    user: UserModel = Depends(require_consent_manage),
    db: Session = Depends(get_db),
):
    """Record DPDP consent granted by a data principal."""
    try:
        categories = [DataCategory(c) for c in request.data_categories]
        purposes = [ProcessingPurpose(p) for p in request.purposes]
    except ValueError as e:
        raise HTTPException(400, detail=f"Invalid category or purpose: {e}")

    manager = DPDPConsentManager(db)
    consent = manager.record_consent(
        user_id=user.id,
        data_categories=categories,
        purposes=purposes,
        consent_text=request.consent_text,
        ip_address=req.client.host if req.client else None,
        user_agent=req.headers.get("user-agent"),
        expires_in_days=request.expires_in_days,
    )

    AuditLogger(db).log_consent(
        AuditAction.CONSENT_GRANTED,
        user_id=user.id,
        consent_id=consent.consent_id,
        details={"categories": request.data_categories, "purposes": request.purposes},
    )

    return ConsentResponse(
        consent_id=consent.consent_id,
        user_id=consent.user_id,
        data_categories=[c.value for c in consent.data_categories],
        purposes=[p.value for p in consent.purposes],
        status=consent.status.value,
        granted_at=consent.granted_at.isoformat() if consent.granted_at else None,
        withdrawn_at=consent.withdrawn_at.isoformat() if consent.withdrawn_at else None,
        expires_at=consent.expires_at.isoformat() if consent.expires_at else None,
        consent_text=consent.consent_text,
    )


@router.post("/compliance/consent/{consent_id}/withdraw")
def withdraw_consent(
    consent_id: str,
    user: UserModel = Depends(require_consent_manage),
    db: Session = Depends(get_db),
):
    """Withdraw DPDP consent (Section 7 right to withdraw)."""
    manager = DPDPConsentManager(db)
    ok = manager.withdraw_consent(consent_id, user.id)
    if not ok:
        raise HTTPException(404, detail="Consent not found")

    AuditLogger(db).log_consent(
        AuditAction.CONSENT_WITHDRAWN,
        user_id=user.id,
        consent_id=consent_id,
    )
    return {"status": "withdrawn", "consent_id": consent_id}


@router.get("/compliance/consent/check")
def check_consent(
    user_id: str = Query(...),
    data_category: str = Query(...),
    purpose: str = Query(...),
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check whether valid consent exists for a data category and purpose."""
    try:
        cat = DataCategory(data_category)
        pur = ProcessingPurpose(purpose)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))

    manager = DPDPConsentManager(db)
    allowed = manager.check_consent(user_id, cat, pur)
    return {"allowed": allowed, "user_id": user_id, "category": data_category, "purpose": purpose}


# ---------------------------------------------------------------------------
# DPDP Retention endpoints
# ---------------------------------------------------------------------------
@router.get("/compliance/retention", response_model=RetentionCheckResponse)
def get_retention_policy(
    data_category: str = Query(...),
    purpose: str = Query(...),
    created_at: Optional[str] = Query(default=None, description="ISO date; defaults to now"),
    user: UserModel = Depends(get_current_user),
):
    """Return retention period and computed expiry for a data category + purpose."""
    try:
        cat = DataCategory(data_category)
        pur = ProcessingPurpose(purpose)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))

    days = RetentionPolicy.get_retention_days(cat, pur)
    base = datetime.fromisoformat(created_at) if created_at else datetime.utcnow()
    expiry = RetentionPolicy.calculate_expiry_date(base, cat, pur)

    return RetentionCheckResponse(
        category=cat.value,
        purpose=pur.value,
        retention_days=days,
        expiry_date=expiry.isoformat(),
    )


@router.post("/compliance/retention/purge")
def run_retention_purge(
    user: UserModel = Depends(require_consent_manage),
    db: Session = Depends(get_db),
):
    """Execute scheduled retention purge (deletes/anonymizes expired data)."""
    from app.compliance.dpdp import RetentionEnforcer
    enforcer = RetentionEnforcer(db)
    results = enforcer.execute_scheduled_deletions()

    AuditLogger(db).log(AuditEntry(
        action=AuditAction.DATA_RETENTION_PURGE,
        actor_id=user.id,
        actor_role=user.role,
        details=results,
    ))
    return results


# ---------------------------------------------------------------------------
# DPDP Data Subject Rights
# ---------------------------------------------------------------------------
@router.get("/compliance/dsar/{principal_id}", response_model=DataSubjectAccessResponse)
def data_subject_access(
    principal_id: str,
    user: UserModel = Depends(require_consent_manage),
    db: Session = Depends(get_db),
):
    """Right to access (DPDP Section 11): return all personal data held."""
    rights = DataSubjectRights(db)
    result = rights.right_to_access(principal_id)

    AuditLogger(db).log(AuditEntry(
        action=AuditAction.DATA_ACCESS_REQUEST,
        actor_id=user.id,
        actor_role=user.role,
        resource_type="data_principal",
        resource_id=principal_id,
    ))
    return DataSubjectAccessResponse(**result)


@router.post("/compliance/dsar/{principal_id}/erasure")
def data_subject_erasure(
    principal_id: str,
    reason: str = Query(...),
    user: UserModel = Depends(require_consent_manage),
    db: Session = Depends(get_db),
):
    """Right to erasure (DPDP Section 13): right to be forgotten."""
    rights = DataSubjectRights(db)
    ok = rights.right_to_erasure(principal_id, reason)

    AuditLogger(db).log(AuditEntry(
        action=AuditAction.DATA_ERASURE_REQUEST,
        actor_id=user.id,
        actor_role=user.role,
        resource_type="data_principal",
        resource_id=principal_id,
        details={"reason": reason, "fulfilled": ok},
    ))
    return {"status": "accepted" if ok else "rejected", "principal_id": principal_id}


@router.post("/compliance/dsar/{principal_id}/correction")
def data_subject_correction(
    principal_id: str,
    corrections: dict,
    user: UserModel = Depends(require_consent_manage),
    db: Session = Depends(get_db),
):
    """Right to correction (DPDP Section 12)."""
    rights = DataSubjectRights(db)
    ok = rights.right_to_correction(principal_id, corrections)

    AuditLogger(db).log(AuditEntry(
        action=AuditAction.DATA_CORRECTION_REQUEST,
        actor_id=user.id,
        actor_role=user.role,
        resource_type="data_principal",
        resource_id=principal_id,
        details={"fields": list(corrections.keys())},
    ))
    return {"status": "accepted" if ok else "rejected"}


# ---------------------------------------------------------------------------
# RBI Contact endpoints
# ---------------------------------------------------------------------------
@router.post("/compliance/contact/check", response_model=ContactCheckResponse)
def check_contact_allowed(
    request: ContactCheckRequest,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pre-contact RBI compliance check: hours, frequency, do-not-contact."""
    try:
        channel = ContactChannel(request.channel)
    except ValueError:
        raise HTTPException(400, detail=f"Invalid channel: {request.channel}")

    enforcer = RBIContactEnforcer(db)
    result = enforcer.check_contact_allowed(
        account_id=request.account_id,
        channel=channel,
        do_not_contact=request.do_not_contact,
        borrower_consented_outside_window=request.borrower_consented_outside_window,
        is_legal_notice=request.is_legal_notice,
    )

    # Persist blocked checks as contact-log entries so the violations
    # endpoint reflects them (auditable, count toward frequency limits).
    if not result.allowed:
        from datetime import datetime
        import uuid
        db.add(ContactLogModel(
            id=f"cl_{uuid.uuid4().hex[:14]}",
            account_id=request.account_id,
            channel=request.channel,
            attempted_at=datetime.utcnow(),
            outcome=ContactOutcome.NOT_REACHED.value,
            agent_id=user.id,
            allowed=False,
            violation_type=result.violations[0].violation_type.value,
            violation_detail=result.reason,
        ))
        db.commit()

    # Audit blocked attempts
    if not result.allowed:
        AuditLogger(db).log_contact(
            account_id=request.account_id,
            allowed=False,
            actor_id=user.id,
            details={"violations": [v.as_dict() for v in result.violations]},
        )

    return ContactCheckResponse(**result.as_dict())


@router.post("/compliance/contact/record")
def record_contact(
    request: ContactRecordRequest,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record a contact attempt (checks rules first, then persists)."""
    try:
        channel = ContactChannel(request.channel)
        outcome = ContactOutcome(request.outcome)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))

    enforcer = RBIContactEnforcer(db)
    entry, check = enforcer.record_attempt(
        account_id=request.account_id,
        channel=channel,
        outcome=outcome,
        agent_id=user.id,
        notes=request.notes,
        do_not_contact=request.do_not_contact,
        is_legal_notice=request.is_legal_notice,
    )

    AuditLogger(db).log_contact(
        account_id=request.account_id,
        allowed=check.allowed,
        actor_id=user.id,
        details={"outcome": outcome.value, "channel": channel.value},
    )

    return {
        "log_id": entry.id,
        "allowed": check.allowed,
        "violations": [v.as_dict() for v in check.violations],
        "attempts_today": check.attempts_today,
        "attempts_this_week": check.attempts_this_week,
    }


@router.get("/compliance/contact/quota/{account_id}")
def contact_quota(
    account_id: str,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remaining RBI contact quota for an account."""
    enforcer = RBIContactEnforcer(db)
    return enforcer.remaining_quota(account_id)


@router.get("/compliance/contact/violations")
def contact_violations(
    account_id: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    user: UserModel = Depends(require_audit_read),
    db: Session = Depends(get_db),
):
    """List recorded RBI contact-rule violations for audit."""
    enforcer = RBIContactEnforcer(db)
    since_dt = datetime.fromisoformat(since) if since else None
    return {"violations": enforcer.get_violations(account_id=account_id, since=since_dt)}


# ---------------------------------------------------------------------------
# Audit log endpoints
# ---------------------------------------------------------------------------
@router.get("/compliance/audit", response_model=List[AuditLogResponse])
def query_audit_log(
    actor_id: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    resource_id: Optional[str] = Query(default=None),
    outcome: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    until: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    user: UserModel = Depends(require_audit_read),
    db: Session = Depends(get_db),
):
    """Search the immutable audit log (RBAC: auditor/admin/lender)."""
    logger = AuditLogger(db)
    rows = logger.search(
        actor_id=actor_id,
        action=action,
        resource_id=resource_id,
        outcome=outcome,
        since=datetime.fromisoformat(since) if since else None,
        until=datetime.fromisoformat(until) if until else None,
        limit=limit,
    )
    return [
        AuditLogResponse(
            id=r.id,
            timestamp=r.timestamp.isoformat(),
            actor_id=r.actor_id,
            actor_role=r.actor_role,
            action=r.action,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            outcome=r.outcome,
            details=r.details,
        )
        for r in rows
    ]


@router.get("/compliance/audit/violation-counts")
def audit_violation_counts(
    since: Optional[str] = Query(default=None),
    user: UserModel = Depends(require_audit_read),
    db: Session = Depends(get_db),
):
    """Count denied/failed actions by type for compliance dashboards."""
    logger = AuditLogger(db)
    counts = logger.count_violations(
        since=datetime.fromisoformat(since) if since else None
    )
    return {"counts": counts}
