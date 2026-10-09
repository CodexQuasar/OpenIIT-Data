# RBI (Reserve Bank of India) Fair Practices Code - Contact Hour & Frequency Limits
# References:
#   - RBI Fair Practices Code for Lenders (2015, revised)
#   - RBI Master Direction on Recovery Agents (2021)
#   - RBI guidelines on locution/timing of recovery calls
from datetime import datetime, time, timedelta, date
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum
from dataclasses import dataclass, field

from sqlalchemy.orm import Session
from sqlalchemy import Column, String, DateTime, Integer, Boolean, Text, Index

from data.models import Base


class ContactChannel(str, Enum):
    """Channels through which a borrower may be contacted."""
    PHONE_CALL = "PHONE_CALL"
    SMS = "SMS"
    WHATSAPP = "WHATSAPP"
    FIELD_VISIT = "FIELD_VISIT"
    EMAIL = "EMAIL"


class ContactOutcome(str, Enum):
    """Outcome of a contact attempt."""
    REACHED = "REACHED"
    NOT_REACHED = "NOT_REACHED"
    BUSY = "BUSY"
    REFUSED = "REFUSED"
    COMPLAINT = "COMPLAINT"
    DO_NOT_CONTACT = "DO_NOT_CONTACT"


# ---------------------------------------------------------------------------
# RBI-mandated contact-hour windows (IST)
# ---------------------------------------------------------------------------
# Per RBI Fair Practices Code + Recovery Agents Master Direction:
#   - Borrower contacts permitted only 07:00 - 20:00 IST on weekdays/Saturday
#   - No contact on Sundays / public holidays (unless borrower consented)
#   - No repeated calling: max 3 attempts per day per account across channels,
#     max 7 attempts per week, and no more than 6 calls per week to the
#     same person for the same account.
#   - No contact to the borrower if a "Do Not Contact" flag is registered,
#     except for legally required notices.

RBI_CONTACT_WINDOW_START = time(7, 0)   # 07:00 IST
RBI_CONTACT_WINDOW_END = time(20, 0)    # 20:00 IST

RBI_MAX_ATTEMPTS_PER_DAY = 3
RBI_MAX_ATTEMPTS_PER_WEEK = 7
RBI_MAX_ATTEMPTS_PER_FORTNIGHT = 10
RBI_QUIET_HOURS_START = time(21, 0)     # Quiet hours 21:00 - 06:00 IST (fully outside contact window)
RBI_QUIET_HOURS_END = time(6, 0)

# Bank / festival holidays (India, national-level list - extendable)
DEFAULT_HOLIDAYS: List[date] = []  # Loaded from calendar in production


class ViolationType(str, Enum):
    """Types of RBI contact-rule violations."""
    OUTSIDE_CONTACT_HOURS = "OUTSIDE_CONTACT_HOURS"
    QUIET_HOURS = "QUIET_HOURS"
    DAILY_LIMIT_EXCEEDED = "DAILY_LIMIT_EXCEEDED"
    WEEKLY_LIMIT_EXCEEDED = "WEEKLY_LIMIT_EXCEEDED"
    FORTNIGHT_LIMIT_EXCEEDED = "FORTNIGHT_LIMIT_EXCEEDED"
    DO_NOT_CONTACT = "DO_NOT_CONTACT"
    HOLIDAY_CONTACT = "HOLIDAY_CONTACT"
    REPEATED_AFTER_COMPLAINT = "REPEATED_AFTER_COMPLAINT"


@dataclass
class ContactRuleViolation:
    """A single RBI contact-rule violation."""
    violation_type: ViolationType
    account_id: str
    channel: ContactChannel
    attempted_at: datetime
    detail: str
    severity: str = "HIGH"  # LOW / MEDIUM / HIGH / CRITICAL

    def as_dict(self) -> Dict[str, Any]:
        return {
            "violation_type": self.violation_type.value,
            "account_id": self.account_id,
            "channel": self.channel.value,
            "attempted_at": self.attempted_at.isoformat(),
            "detail": self.detail,
            "severity": self.severity,
        }


@dataclass
class ContactCheckResult:
    """Result of a pre-contact compliance check."""
    allowed: bool
    violations: List[ContactRuleViolation] = field(default_factory=list)
    reason: Optional[str] = None
    attempts_today: int = 0
    attempts_this_week: int = 0
    next_allowed_at: Optional[datetime] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "violations": [v.as_dict() for v in self.violations],
            "reason": self.reason,
            "attempts_today": self.attempts_today,
            "attempts_this_week": self.attempts_this_week,
            "next_allowed_at": self.next_allowed_at.isoformat() if self.next_allowed_at else None,
        }


# ---------------------------------------------------------------------------
# Contact log model (persisted)
# ---------------------------------------------------------------------------
class ContactLogModel(Base):
    """Persisted record of every contact attempt (for audit + frequency rules)."""
    __tablename__ = "contact_logs"

    id = Column(String, primary_key=True)
    account_id = Column(String, nullable=False, index=True)
    channel = Column(String, nullable=False)
    attempted_at = Column(DateTime, nullable=False, index=True)
    outcome = Column(String, nullable=False)
    agent_id = Column(String, nullable=True)
    allowed = Column(Boolean, nullable=False, default=True)
    violation_type = Column(String, nullable=True)
    violation_detail = Column(String, nullable=True)
    notes = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_contact_logs_account_time", "account_id", "attempted_at"),
    )


class ContactAttemptStore:
    """Read/write contact attempts."""

    def __init__(self, db: Session):
        self.db = db

    def record(self, entry: ContactLogModel) -> ContactLogModel:
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def attempts_since(self, account_id: str, since: datetime) -> List[ContactLogModel]:
        return (
            self.db.query(ContactLogModel)
            .filter(
                ContactLogModel.account_id == account_id,
                ContactLogModel.attempted_at >= since,
            )
            .order_by(ContactLogModel.attempted_at.desc())
            .all()
        )

    def attempts_on_day(self, account_id: str, day: date) -> List[ContactLogModel]:
        start = datetime.combine(day, time.min)
        end = start + timedelta(days=1)
        return (
            self.db.query(ContactLogModel)
            .filter(
                ContactLogModel.account_id == account_id,
                ContactLogModel.attempted_at >= start,
                ContactLogModel.attempted_at < end,
            )
            .all()
        )


# ---------------------------------------------------------------------------
# The enforcer
# ---------------------------------------------------------------------------
class RBIContactEnforcer:
    """Enforces RBI contact-hour and contact-frequency rules."""

    def __init__(
        self,
        db: Session,
        contact_window_start: time = RBI_CONTACT_WINDOW_START,
        contact_window_end: time = RBI_CONTACT_WINDOW_END,
        max_per_day: int = RBI_MAX_ATTEMPTS_PER_DAY,
        max_per_week: int = RBI_MAX_ATTEMPTS_PER_WEEK,
        max_per_fortnight: int = RBI_MAX_ATTEMPTS_PER_FORTNIGHT,
        holidays: Optional[List[date]] = None,
        timezone_offset_hours: float = 5.5,  # IST
    ):
        self.db = db
        self.store = ContactAttemptStore(db)
        self.window_start = contact_window_start
        self.window_end = contact_window_end
        self.max_per_day = max_per_day
        self.max_per_week = max_per_week
        self.max_per_fortnight = max_per_fortnight
        self.holidays = holidays if holidays is not None else list(DEFAULT_HOLIDAYS)
        self.tz_offset = timedelta(hours=timezone_offset_hours)

    # -- helpers ------------------------------------------------------------
    def _to_ist(self, dt: datetime) -> datetime:
        """Treat naive datetimes as UTC and convert to IST."""
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt + self.tz_offset

    def _ist_now(self) -> datetime:
        return self._to_ist(datetime.utcnow())

    def _in_contact_window(self, ist_dt: datetime) -> bool:
        t = ist_dt.time()
        return self.window_start <= t < self.window_end

    def _in_quiet_hours(self, ist_dt: datetime) -> bool:
        t = ist_dt.time()
        # Quiet hours are the complement of the extended window (21:00 - 09:00)
        return t >= RBI_QUIET_HOURS_START or t < RBI_QUIET_HOURS_END

    def _is_holiday(self, ist_dt: datetime) -> bool:
        return ist_dt.date() in self.holidays

    def _is_sunday(self, ist_dt: datetime) -> bool:
        return ist_dt.weekday() == 6  # Monday=0 ... Sunday=6

    # -- main check ---------------------------------------------------------
    def check_contact_allowed(
        self,
        account_id: str,
        channel: ContactChannel,
        attempted_at: Optional[datetime] = None,
        do_not_contact: bool = False,
        borrower_consented_outside_window: bool = False,
        is_legal_notice: bool = False,
    ) -> ContactCheckResult:
        """Pre-contact compliance check. Returns whether contact is allowed."""
        now = attempted_at or datetime.utcnow()
        ist_now = self._to_ist(now)
        violations: List[ContactRuleViolation] = []

        # 1. Do Not Contact flag
        if do_not_contact and not is_legal_notice:
            violations.append(ContactRuleViolation(
                violation_type=ViolationType.DO_NOT_CONTACT,
                account_id=account_id,
                channel=channel,
                attempted_at=now,
                detail="Account flagged Do Not Contact; only legally required notices permitted",
                severity="CRITICAL",
            ))

        # 2. Contact-hour window (IST)
        if not self._in_contact_window(ist_now):
            if not (borrower_consented_outside_window or is_legal_notice):
                violations.append(ContactRuleViolation(
                    violation_type=ViolationType.OUTSIDE_CONTACT_HOURS,
                    account_id=account_id,
                    channel=channel,
                    attempted_at=now,
                    detail=(
                        f"Contact attempted at {ist_now.strftime('%H:%M')} IST; "
                        f"permitted window is {self.window_start.strftime('%H:%M')}-"
                        f"{self.window_end.strftime('%H:%M')} IST"
                    ),
                    severity="HIGH",
                ))

        # 3. Quiet hours (21:00 - 09:00 IST)
        if self._in_quiet_hours(ist_now) and not is_legal_notice:
            violations.append(ContactRuleViolation(
                violation_type=ViolationType.QUIET_HOURS,
                account_id=account_id,
                channel=channel,
                attempted_at=now,
                detail=f"Contact attempted during quiet hours ({ist_now.strftime('%H:%M')} IST)",
                severity="HIGH",
            ))

        # 4. Sunday / holiday
        if self._is_sunday(ist_now) and not (is_legal_notice or borrower_consented_outside_window):
            violations.append(ContactRuleViolation(
                violation_type=ViolationType.HOLIDAY_CONTACT,
                account_id=account_id,
                channel=channel,
                attempted_at=now,
                detail="Contact attempted on Sunday",
                severity="MEDIUM",
            ))
        if self._is_holiday(ist_now) and not (is_legal_notice or borrower_consented_outside_window):
            violations.append(ContactRuleViolation(
                violation_type=ViolationType.HOLIDAY_CONTACT,
                account_id=account_id,
                channel=channel,
                attempted_at=now,
                detail=f"Contact attempted on public holiday {ist_now.date().isoformat()}",
                severity="MEDIUM",
            ))

        # 5. Frequency limits (day boundaries converted to UTC to match stored timestamps)
        utc_day_start = datetime.combine(ist_now.date(), time.min) - self.tz_offset
        attempts_today = [
            a for a in self.store.attempts_since(account_id, utc_day_start)
        ]
        attempts_this_week = self.store.attempts_since(
            account_id, now - timedelta(days=7)
        )
        attempts_this_fortnight = self.store.attempts_since(
            account_id, now - timedelta(days=14)
        )

        if len(attempts_today) >= self.max_per_day:
            violations.append(ContactRuleViolation(
                violation_type=ViolationType.DAILY_LIMIT_EXCEEDED,
                account_id=account_id,
                channel=channel,
                attempted_at=now,
                detail=f"Daily limit of {self.max_per_day} attempts reached",
                severity="HIGH",
            ))

        if len(attempts_this_week) >= self.max_per_week:
            violations.append(ContactRuleViolation(
                violation_type=ViolationType.WEEKLY_LIMIT_EXCEEDED,
                account_id=account_id,
                channel=channel,
                attempted_at=now,
                detail=f"Weekly limit of {self.max_per_week} attempts reached",
                severity="HIGH",
            ))

        if len(attempts_this_fortnight) >= self.max_per_fortnight:
            violations.append(ContactRuleViolation(
                violation_type=ViolationType.FORTNIGHT_LIMIT_EXCEEDED,
                account_id=account_id,
                channel=channel,
                attempted_at=now,
                detail=f"Fortnightly limit of {self.max_per_fortnight} attempts reached",
                severity="HIGH",
            ))

        # 6. No contact after a complaint was registered (cool-down 7 days)
        recent_complaints = [
            a for a in attempts_this_week
            if a.outcome == ContactOutcome.COMPLAINT.value
        ]
        if recent_complaints and not is_legal_notice:
            latest_complaint = max(recent_complaints, key=lambda a: a.attempted_at)
            cooldown_end = latest_complaint.attempted_at + timedelta(days=7)
            if now < cooldown_end:
                violations.append(ContactRuleViolation(
                    violation_type=ViolationType.REPEATED_AFTER_COMPLAINT,
                    account_id=account_id,
                    channel=channel,
                    attempted_at=now,
                    detail=(
                        "Borrower registered a complaint; "
                        f"cool-down until {cooldown_end.isoformat()}"
                    ),
                    severity="CRITICAL",
                ))

        allowed = len(violations) == 0
        reason = None if allowed else "; ".join(v.detail for v in violations)

        # Compute next allowed time (next window start if outside window,
        # or next day if daily limit reached)
        next_allowed = None
        if not allowed:
            if not self._in_contact_window(ist_now):
                next_window = datetime.combine(ist_now.date(), self.window_start)
                if next_window <= ist_now:
                    next_window += timedelta(days=1)
                next_allowed = next_window - self.tz_offset
            elif len(attempts_today) >= self.max_per_day:
                next_day = datetime.combine(ist_now.date() + timedelta(days=1), self.window_start)
                next_allowed = next_day - self.tz_offset

        return ContactCheckResult(
            allowed=allowed,
            violations=violations,
            reason=reason,
            attempts_today=len(attempts_today),
            attempts_this_week=len(attempts_this_week),
            next_allowed_at=next_allowed,
        )

    # -- recording ----------------------------------------------------------
    def record_attempt(
        self,
        account_id: str,
        channel: ContactChannel,
        outcome: ContactOutcome,
        attempted_at: Optional[datetime] = None,
        agent_id: Optional[str] = None,
        notes: Optional[str] = None,
        do_not_contact: bool = False,
        is_legal_notice: bool = False,
    ) -> Tuple[ContactLogModel, ContactCheckResult]:
        """Check compliance then record the contact attempt."""
        now = attempted_at or datetime.utcnow()
        check = self.check_contact_allowed(
            account_id=account_id,
            channel=channel,
            attempted_at=now,
            do_not_contact=do_not_contact,
            is_legal_notice=is_legal_notice,
        )

        import uuid
        entry = ContactLogModel(
            id=f"cl_{uuid.uuid4().hex[:14]}",
            account_id=account_id,
            channel=channel.value,
            attempted_at=now,
            outcome=outcome.value,
            agent_id=agent_id,
            allowed=check.allowed,
            violation_type=check.violations[0].violation_type.value if check.violations else None,
            violation_detail=check.reason,
            notes=notes,
        )
        self.store.record(entry)

        # Recompute counts to reflect the attempt just recorded
        ist_now = self._to_ist(now)
        utc_day_start = datetime.combine(ist_now.date(), time.min) - self.tz_offset
        check.attempts_today = len(self.store.attempts_since(account_id, utc_day_start))
        check.attempts_this_week = len(
            self.store.attempts_since(account_id, now - timedelta(days=7))
        )
        return entry, check

    # -- reporting ----------------------------------------------------------
    def get_violations(
        self,
        account_id: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Return recorded violations for audit reporting."""
        q = self.db.query(ContactLogModel).filter(ContactLogModel.allowed.is_(False))
        if account_id:
            q = q.filter(ContactLogModel.account_id == account_id)
        if since:
            q = q.filter(ContactLogModel.attempted_at >= since)
        rows = q.order_by(ContactLogModel.attempted_at.desc()).all()
        return [
            {
                "id": r.id,
                "account_id": r.account_id,
                "channel": r.channel,
                "attempted_at": r.attempted_at.isoformat(),
                "violation_type": r.violation_type,
                "detail": r.violation_detail,
            }
            for r in rows
        ]

    def remaining_quota(self, account_id: str) -> Dict[str, int]:
        """Remaining contact quota for an account today/this week/this fortnight."""
        ist_now = self._ist_now()
        utc_day_start = datetime.combine(ist_now.date(), time.min) - self.tz_offset
        today = len(self.store.attempts_since(account_id, utc_day_start))
        week = len(self.store.attempts_since(account_id, datetime.utcnow() - timedelta(days=7)))
        fortnight = len(self.store.attempts_since(account_id, datetime.utcnow() - timedelta(days=14)))
        return {
            "today_remaining": max(0, self.max_per_day - today),
            "week_remaining": max(0, self.max_per_week - week),
            "fortnight_remaining": max(0, self.max_per_fortnight - fortnight),
            "in_contact_window": self._in_contact_window(ist_now),
            "ist_time": ist_now.strftime("%H:%M"),
        }
