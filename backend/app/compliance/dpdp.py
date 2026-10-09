# DPDP (Digital Personal Data Protection) Act Compliance Module
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from sqlalchemy import Column, String, DateTime, Boolean, Text, Integer, ForeignKey, Index, Enum as SQLEnum
from sqlalchemy.orm import relationship

from data.models import Base
from data.database import get_db
from config.settings import get_settings


class ConsentStatus(str, Enum):
    """Consent status enum."""
    GRANTED = "GRANTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    PENDING = "PENDING"


class DataCategory(str, Enum):
    """Categories of personal data under DPDP."""
    IDENTITY = "IDENTITY"           # Name, ID numbers, etc.
    CONTACT = "CONTACT"             # Phone, email, address
    FINANCIAL = "FINANCIAL"         # Account numbers, transaction history
    LOCATION = "LOCATION"           # GPS coordinates, visit history
    BIOMETRIC = "BIOMETRIC"         # Photos, fingerprints (if any)
    BEHAVIORAL = "BEHAVIORAL"       # Visit patterns, interaction history
    DEMOGRAPHIC = "DEMOGRAPHIC"     # Age, gender, income type


class ProcessingPurpose(str, Enum):
    """Lawful purposes for data processing under DPDP."""
    DEBT_COLLECTION = "DEBT_COLLECTION"           # Primary purpose
    LEGAL_COMPLIANCE = "LEGAL_COMPLIANCE"         # Regulatory requirements
    FRAUD_PREVENTION = "FRAUD_PREVENTION"         # Security/fraud
    SERVICE_IMPROVEMENT = "SERVICE_IMPROVEMENT"   # Analytics (with consent)
    MARKETING = "MARKETING"                       # Marketing (requires explicit consent)
    RESEARCH = "RESEARCH"                         # Research (with consent)


@dataclass
class ConsentRecord:
    """Consent record for DPDP compliance."""
    consent_id: str
    user_id: str  # Can be borrower (data principal) or agent (data processor)
    data_categories: List[DataCategory]
    purposes: List[ProcessingPurpose]
    status: ConsentStatus
    granted_at: Optional[datetime] = None
    withdrawn_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    consent_text: str = ""  # The actual consent text shown to user
    version: str = "1.0"
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class DPDPConsentManager:
    """Manages DPDP consent lifecycle."""

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    def record_consent(
        self,
        user_id: str,
        data_categories: List[DataCategory],
        purposes: List[ProcessingPurpose],
        consent_text: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        expires_in_days: Optional[int] = None,
    ) -> ConsentRecord:
        """Record new consent from data principal."""
        import uuid
        consent_id = f"consent_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()
        
        expires_at = None
        if expires_in_days:
            expires_at = now + timedelta(days=expires_in_days)
        
        consent = ConsentRecord(
            consent_id=consent_id,
            user_id=user_id,
            data_categories=data_categories,
            purposes=purposes,
            status=ConsentStatus.GRANTED,
            granted_at=now,
            expires_at=expires_at,
            consent_text=consent_text,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        
        # Store in database (would need ConsentModel)
        # self._store_consent(consent)
        
        return consent

    def withdraw_consent(
        self,
        consent_id: str,
        user_id: str,
        reason: Optional[str] = None,
    ) -> bool:
        """Withdraw consent (Right to withdraw under DPDP Section 7)."""
        # Implementation would update consent status to WITHDRAWN
        # and trigger data processing cessation for affected purposes
        return True

    def check_consent(
        self,
        user_id: str,
        data_category: DataCategory,
        purpose: ProcessingPurpose,
    ) -> bool:
        """Check if valid consent exists for data category and purpose."""
        # Implementation would query active consents
        return True

    def get_active_consents(self, user_id: str) -> List[ConsentRecord]:
        """Get all active consents for a user."""
        return []

    def get_expired_consents(self) -> List[ConsentRecord]:
        """Get all expired consents for renewal notifications."""
        return []


class RetentionPolicy:
    """Data retention policies per DPDP and RBI guidelines."""

    # Retention periods in days
    RETENTION_PERIODS = {
        DataCategory.IDENTITY: 2555,      # 7 years (RBI KYC)
        DataCategory.CONTACT: 2555,       # 7 years
        DataCategory.FINANCIAL: 2555,     # 7 years (RBI)
        DataCategory.LOCATION: 1095,      # 3 years (operational)
        DataCategory.BIOMETRIC: 1095,     # 3 years
        DataCategory.BEHAVIORAL: 1095,    # 3 years
        DataCategory.DEMOGRAPHIC: 2555,   # 7 years
    }

    # Special retention for specific purposes
    PURPOSE_RETENTION = {
        ProcessingPurpose.DEBT_COLLECTION: 2555,
        ProcessingPurpose.LEGAL_COMPLIANCE: 2555,
        ProcessingPurpose.FRAUD_PREVENTION: 1095,
        ProcessingPurpose.SERVICE_IMPROVEMENT: 1095,
        ProcessingPurpose.MARKETING: 730,   # 2 years
        ProcessingPurpose.RESEARCH: 1095,
    }

    @classmethod
    def get_retention_days(
        cls,
        data_category: DataCategory,
        purpose: ProcessingPurpose,
    ) -> int:
        """Get retention period in days for data category and purpose."""
        category_retention = cls.RETENTION_PERIODS.get(data_category, 1095)
        purpose_retention = cls.PURPOSE_RETENTION.get(purpose, 1095)
        return max(category_retention, purpose_retention)

    @classmethod
    def calculate_expiry_date(
        cls,
        created_at: datetime,
        data_category: DataCategory,
        purpose: ProcessingPurpose,
    ) -> datetime:
        """Calculate expiry date for data retention."""
        days = cls.get_retention_days(data_category, purpose)
        return created_at + timedelta(days=days)


class RetentionEnforcer:
    """Enforces data retention policies."""

    def __init__(self, db: Session):
        self.db = db

    def find_expired_data(self) -> List[Dict[str, Any]]:
        """Find all data that has exceeded retention period."""
        expired_items = []
        
        # Check accounts
        # expired_accounts = self.db.query(AccountModel).filter(
        #     AccountModel.created_at < datetime.utcnow() - timedelta(days=2555)
        # ).all()
        
        # Check visits
        # expired_visits = self.db.query(VisitModel).filter(
        #     VisitModel.timestamp < datetime.utcnow() - timedelta(days=1095)
        # ).all()
        
        # Check predictions
        # expired_predictions = self.db.query(PredictionModel).filter(
        #     PredictionModel.timestamp < datetime.utcnow() - timedelta(days=1095)
        # ).all()
        
        return expired_items

    def schedule_deletion(self, entity_type: str, entity_id: str, reason: str) -> bool:
        """Schedule data for deletion (soft delete with audit trail)."""
        # Implementation would mark for deletion and schedule actual deletion
        return True

    def execute_scheduled_deletions(self) -> Dict[str, int]:
        """Execute all scheduled deletions."""
        results = {
            "accounts_deleted": 0,
            "visits_deleted": 0,
            "predictions_deleted": 0,
            "errors": 0,
        }
        
        # Implementation would process deletion queue
        # with proper audit logging
        
        return results

    def anonymize_expired_data(self) -> Dict[str, int]:
        """Anonymize data that can't be deleted due to legal hold."""
        # For data that must be retained but personal identifiers removed
        results = {
            "accounts_anonymized": 0,
            "visits_anonymized": 0,
        }
        return results


class DataSubjectRights:
    """Implements DPDP Data Subject Rights (Sections 11-15)."""

    def __init__(self, db: Session):
        self.db = db
        self.consent_manager = DPDPConsentManager(db)
        self.retention_enforcer = RetentionEnforcer(db)

    def right_to_access(self, user_id: str) -> Dict[str, Any]:
        """Right to access personal data (Section 11)."""
        return {
            "personal_data": {},
            "processing_purposes": [],
            "data_categories": [],
            "recipients": [],
            "retention_periods": {},
            "source": "direct",
        }

    def right_to_correction(self, user_id: str, corrections: Dict[str, Any]) -> bool:
        """Right to correction (Section 12)."""
        # Implementation would update personal data
        return True

    def right_to_erasure(self, user_id: str, reason: str) -> bool:
        """Right to erasure (Section 13) - Right to be forgotten."""
        # Check if legal basis exists to retain
        # If not, schedule for deletion/anonymization
        return True

    def right_to_nominee(self, user_id: str, nominee_id: str) -> bool:
        """Right to nominate (Section 14) - for incapacitated/deceased."""
        return True

    def right_to_grievance(self, user_id: str, grievance: str) -> str:
        """Right to grievance redressal (Section 15)."""
        # Create grievance ticket
        grievance_id = f"grv_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        return grievance_id


class DataProtectionImpactAssessment:
    """DPIA for high-risk processing (DPDP Section 10)."""

    def __init__(self):
        self.assessments: Dict[str, Dict] = {}

    def assess_processing(
        self,
        processing_name: str,
        data_categories: List[DataCategory],
        purposes: List[ProcessingPurpose],
        scale: str,  # "small", "medium", "large"
        technology: str,
    ) -> Dict[str, Any]:
        """Conduct DPIA for new processing activity."""
        risk_level = self._calculate_risk(data_categories, purposes, scale)
        
        assessment = {
            "assessment_id": f"dpia_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            "processing_name": processing_name,
            "data_categories": [c.value for c in data_categories],
            "purposes": [p.value for p in purposes],
            "scale": scale,
            "technology": technology,
            "risk_level": risk_level,
            "mitigation_measures": self._get_mitigations(risk_level),
            "approved": risk_level != "high",
            "review_date": datetime.utcnow() + timedelta(days=365),
            "created_at": datetime.utcnow(),
        }
        
        self.assessments[assessment["assessment_id"]] = assessment
        return assessment

    def _calculate_risk(
        self,
        data_categories: List[DataCategory],
        purposes: List[ProcessingPurpose],
        scale: str,
    ) -> str:
        """Calculate risk level for DPIA."""
        risk_score = 0
        
        # High-risk categories
        high_risk_cats = {DataCategory.BIOMETRIC, DataCategory.FINANCIAL, DataCategory.LOCATION}
        for cat in data_categories:
            if cat in high_risk_cats:
                risk_score += 2
            else:
                risk_score += 1
        
        # Scale factor
        scale_factors = {"small": 1, "medium": 2, "large": 3}
        risk_score *= scale_factors.get(scale, 1)
        
        # Purpose sensitivity
        sensitive_purposes = {ProcessingPurpose.MARKETING, ProcessingPurpose.RESEARCH}
        for purpose in purposes:
            if purpose in sensitive_purposes:
                risk_score += 2
        
        if risk_score >= 15:
            return "high"
        elif risk_score >= 8:
            return "medium"
        return "low"

    def _get_mitigations(self, risk_level: str) -> List[str]:
        """Get mitigation measures for risk level."""
        base = [
            "Data minimization applied",
            "Purpose limitation enforced",
            "Access controls implemented",
            "Encryption at rest and in transit",
            "Regular security audits",
            "Staff training on data protection",
        ]
        
        if risk_level == "high":
            base.extend([
                "DPO consultation required",
                "Explicit consent for each purpose",
                "Enhanced monitoring and alerting",
                "Data Protection Impact Assessment review quarterly",
            ])
        elif risk_level == "medium":
            base.extend([
                "DPO notification required",
                "Semi-annual review",
            ])
        
        return base


# Consent text templates for DPDP compliance
DPDP_CONSENT_TEMPLATES = {
    ProcessingPurpose.DEBT_COLLECTION: {
        "title": "Consent for Debt Collection Processing",
        "text": (
            "We collect and process your personal data including identity, contact, financial, "
            "and location information for the purpose of debt collection activities. "
            "This processing is necessary for the performance of our contractual obligations "
            "and compliance with legal requirements. Your data will be retained for 7 years "
            "as per RBI guidelines. You have the right to access, correct, and request erasure "
            "of your data (subject to legal obligations)."
        ),
        "categories": [
            DataCategory.IDENTITY,
            DataCategory.CONTACT,
            DataCategory.FINANCIAL,
            DataCategory.LOCATION,
        ],
    },
    ProcessingPurpose.SERVICE_IMPROVEMENT: {
        "title": "Consent for Service Improvement Analytics",
        "text": (
            "We would like to use your behavioral and interaction data to improve our services "
            "and field operations. This includes visit patterns, response times, and outcome "
            "analytics. This data will be aggregated and anonymized where possible. "
            "You can withdraw this consent at any time without affecting debt collection services."
        ),
        "categories": [
            DataCategory.BEHAVIORAL,
            DataCategory.DEMOGRAPHIC,
        ],
    },
    ProcessingPurpose.MARKETING: {
        "title": "Consent for Marketing Communications",
        "text": (
            "We may send you updates about new services, policy changes, or financial literacy "
            "content. Your contact information will only be used for this purpose. "
            "You can unsubscribe at any time."
        ),
        "categories": [
            DataCategory.CONTACT,
            DataCategory.DEMOGRAPHIC,
        ],
    },
}


def get_consent_template(purpose: ProcessingPurpose) -> Dict[str, Any]:
    """Get consent template for a processing purpose."""
    return DPDP_CONSENT_TEMPLATES.get(purpose, {
        "title": f"Consent for {purpose.value}",
        "text": "We process your personal data for the stated purpose.",
        "categories": [],
    })