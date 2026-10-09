"""Data access layer repositories."""

import json
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from data.models import (
    AccountModel, VisitModel, PredictionModel, 
    PlaceClusterModel, CacheEntryModel, GeocoderCacheModel, EmbeddingCacheModel
)
from app.schemas import (
    Account, Visit, VisitOutcome, CandidateSource, 
    RecommendedAction, Prediction, PredictionEvidence,
    CandidateLocation, TrajectoryPoint, NormalizedAddress, AddressEntity
)


class AccountRepository:
    """Repository for account operations."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, account: Account) -> AccountModel:
        """Create a new account."""
        model = AccountModel(
            account_id=account.account_id,
            address=account.address,
            normalized_address=account.normalized_address.model_dump_json() if account.normalized_address else None,
            language=account.language,
            pincode=account.pincode,
            locality=account.locality,
            city=account.city,
            state=account.state,
            town_id=account.town_id,
            place_cluster_id=account.place_cluster_id,
            latitude=account.latitude,
            longitude=account.longitude,
            confidence=account.confidence,
            confidence_radius_m=account.confidence_radius_m,
            location_source=account.location_source,
            location_crs=account.location_crs,
            confirmed_latitude=account.confirmed_latitude,
            confirmed_longitude=account.confirmed_longitude,
            confirmed_radius_m=account.confirmed_radius_m,
            confirmed_at=account.confirmed_at,
            location_updated_at=account.location_updated_at,
        )
        self.db.add(model)
        self.db.flush()
        return model

    def get_by_id(self, account_id: str) -> Optional[AccountModel]:
        """Get account by ID."""
        return self.db.query(AccountModel).filter(AccountModel.account_id == account_id).first()

    def get_all(self, limit: int = 100, offset: int = 0) -> list[AccountModel]:
        """Get all accounts with pagination."""
        return self.db.query(AccountModel).offset(offset).limit(limit).all()

    def search(self, query: str, limit: int = 50) -> list[AccountModel]:
        """Search accounts by address, locality, pincode."""
        search_term = f"%{query}%"
        return self.db.query(AccountModel).filter(
            or_(
                AccountModel.address.ilike(search_term),
                AccountModel.locality.ilike(search_term),
                AccountModel.pincode.ilike(search_term),
                AccountModel.city.ilike(search_term),
            )
        ).limit(limit).all()

    def get_by_place_cluster(self, cluster_id: str) -> list[AccountModel]:
        """Get accounts in a place cluster."""
        return self.db.query(AccountModel).filter(
            AccountModel.place_cluster_id == cluster_id
        ).all()

    def update_location(self, account_id: str, lat: float, lon: float, 
                        confidence: float, radius_m: float, cluster_id: Optional[str] = None,
                        source: str = "prediction", coordinate_crs: str = "WGS84") -> bool:
        """Update account predicted location."""
        account = self.get_by_id(account_id)
        if not account:
            return False
        if source == "visit_confirmed" or account.confirmed_latitude is None:
            account.latitude = lat
            account.longitude = lon
            account.confidence = confidence
            account.confidence_radius_m = radius_m
        if cluster_id:
            account.place_cluster_id = cluster_id
        account.location_source = source if source == "visit_confirmed" or account.confirmed_latitude is None else "visit_confirmed"
        account.location_crs = coordinate_crs
        if source == "visit_confirmed":
            account.confirmed_latitude = lat
            account.confirmed_longitude = lon
            account.confirmed_radius_m = radius_m
            account.confirmed_at = datetime.utcnow()
        else:
            account.predicted_latitude = lat
            account.predicted_longitude = lon
            account.predicted_radius_m = radius_m
            account.predicted_at = datetime.utcnow()
        account.location_updated_at = datetime.utcnow()
        account.updated_at = datetime.utcnow()
        return True

    def count(self) -> int:
        """Count total accounts."""
        return self.db.query(AccountModel).count()

    def get_nearby_accounts(self, lat: float, lon: float, radius_m: float = 1000, limit: int = 20) -> list[AccountModel]:
        """Get accounts near a location using bounding box approximation."""
        # Rough degree conversion: 1 degree ~= 111km at equator
        deg = radius_m / 111000
        return self.db.query(AccountModel).filter(
            AccountModel.latitude.isnot(None),
            AccountModel.longitude.isnot(None),
            AccountModel.latitude.between(lat - deg, lat + deg),
            AccountModel.longitude.between(lon - deg, lon + deg),
        ).limit(limit).all()


class VisitRepository:
    """Repository for visit operations."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, visit: Visit) -> VisitModel:
        """Create a new visit."""
        trajectory_json = json.dumps([t.model_dump() for t in visit.trajectory]) if visit.trajectory else None
        model = VisitModel(
            visit_id=visit.visit_id,
            account_id=visit.account_id,
            agent_id=visit.agent_id,
            timestamp=visit.timestamp,
            latitude=visit.latitude,
            longitude=visit.longitude,
            gps_accuracy=visit.gps_accuracy,
            outcome=visit.outcome,
            dwell_time=visit.dwell_time,
            remarks=visit.remarks,
            trajectory=trajectory_json,
            integrity_score=visit.integrity_score,
            reliability_score=visit.reliability_score,
            remark_correction=visit.remark_correction,
            coordinate_crs=visit.coordinate_crs,
        )
        self.db.add(model)
        self.db.flush()
        return model

    def get_by_id(self, visit_id: str) -> Optional[VisitModel]:
        """Get visit by ID."""
        return self.db.query(VisitModel).filter(VisitModel.visit_id == visit_id).first()

    def get_by_account(self, account_id: str, limit: int = 100) -> list[VisitModel]:
        """Get visits for an account, ordered by timestamp desc."""
        return self.db.query(VisitModel).filter(
            VisitModel.account_id == account_id
        ).order_by(VisitModel.timestamp.desc()).limit(limit).all()

    def get_by_account_before(self, account_id: str, before: datetime, limit: int = 100) -> list[VisitModel]:
        """Get visits for an account before a timestamp (for time-aware evaluation)."""
        return self.db.query(VisitModel).filter(
            and_(
                VisitModel.account_id == account_id,
                VisitModel.timestamp < before
            )
        ).order_by(VisitModel.timestamp.desc()).limit(limit).all()

    def get_by_agent(self, agent_id: str, limit: int = 100) -> list[VisitModel]:
        """Get visits by agent."""
        return self.db.query(VisitModel).filter(
            VisitModel.agent_id == agent_id
        ).order_by(VisitModel.timestamp.desc()).limit(limit).all()

    def get_successful_visits(self, account_id: str, limit: int = 50) -> list[VisitModel]:
        """Get successful visits for an account."""
        return self.db.query(VisitModel).filter(
            and_(
                VisitModel.account_id == account_id,
                VisitModel.outcome.in_([
                    VisitOutcome.SUCCESSFUL_CONTACT,
                    VisitOutcome.PARTIAL_CONTACT
                ])
            )
        ).order_by(VisitModel.timestamp.desc()).limit(limit).all()

    def get_all_successful(self, limit: int = 1000) -> list[VisitModel]:
        """Get all successful visits."""
        return self.db.query(VisitModel).filter(
            VisitModel.outcome.in_([
                VisitOutcome.SUCCESSFUL_CONTACT,
                VisitOutcome.PARTIAL_CONTACT
            ])
        ).order_by(VisitModel.timestamp.desc()).limit(limit).all()

    def count_by_account(self, account_id: str) -> int:
        """Count visits for an account."""
        return self.db.query(VisitModel).filter(VisitModel.account_id == account_id).count()

    def count_successful_by_account(self, account_id: str) -> int:
        """Count successful visits for an account."""
        return self.db.query(VisitModel).filter(
            and_(
                VisitModel.account_id == account_id,
                VisitModel.outcome.in_([
                    VisitOutcome.SUCCESSFUL_CONTACT,
                    VisitOutcome.PARTIAL_CONTACT
                ])
            )
        ).count()


class PredictionRepository:
    """Repository for prediction operations."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, prediction: Prediction) -> PredictionModel:
        """Create a new prediction."""
        evidence_json = prediction.evidence.model_dump_json() if prediction.evidence else None
        candidates_json = json.dumps([c.model_dump() for c in prediction.candidates]) if prediction.candidates else None
        
        model = PredictionModel(
            prediction_id=f"pred_{uuid4().hex[:12]}",
            account_id=prediction.account_id,
            latitude=prediction.latitude,
            longitude=prediction.longitude,
            confidence=prediction.confidence,
            confidence_radius_m=prediction.confidence_radius_m,
            prediction_method=prediction.prediction_method,
            recommended_action=prediction.recommended_action,
            directions=prediction.directions,
            evidence=evidence_json,
            model_version=prediction.model_version,
            feature_version=prediction.feature_version,
            candidates=candidates_json,
            timestamp=prediction.timestamp,
        )
        self.db.add(model)
        self.db.flush()
        return model

    def get_latest_by_account(self, account_id: str) -> Optional[PredictionModel]:
        """Get latest prediction for an account."""
        return self.db.query(PredictionModel).filter(
            PredictionModel.account_id == account_id
        ).order_by(PredictionModel.timestamp.desc()).first()

    def get_history(self, account_id: str, limit: int = 20) -> list[PredictionModel]:
        """Get prediction history for an account."""
        return self.db.query(PredictionModel).filter(
            PredictionModel.account_id == account_id
        ).order_by(PredictionModel.timestamp.desc()).limit(limit).all()


class PlaceClusterRepository:
    """Repository for place cluster operations."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, cluster: "PlaceCluster") -> PlaceClusterModel:
        """Create a new place cluster."""
        import json
        model = PlaceClusterModel(
            cluster_id=cluster.cluster_id,
            latitude=cluster.latitude,
            longitude=cluster.longitude,
            account_ids=json.dumps(cluster.account_ids),
            landmarks=json.dumps(cluster.landmarks) if cluster.landmarks else None,
            address_variants=json.dumps(cluster.address_variants) if cluster.address_variants else None,
            visit_count=cluster.visit_count,
            confidence=cluster.confidence,
        )
        self.db.add(model)
        self.db.flush()
        return model

    def get_by_id(self, cluster_id: str) -> Optional[PlaceClusterModel]:
        """Get cluster by ID."""
        return self.db.query(PlaceClusterModel).filter(PlaceClusterModel.cluster_id == cluster_id).first()

    def get_all(self, limit: int = 100) -> list[PlaceClusterModel]:
        """Get all clusters."""
        return self.db.query(PlaceClusterModel).limit(limit).all()

    def get_nearby(self, lat: float, lon: float, radius_m: float = 500) -> list[PlaceClusterModel]:
        """Get clusters near a location (approximate with bounding box)."""
        # Rough degree conversion: 1 degree ~= 111km
        deg = radius_m / 111000
        return self.db.query(PlaceClusterModel).filter(
            and_(
                PlaceClusterModel.latitude.between(lat - deg, lat + deg),
                PlaceClusterModel.longitude.between(lon - deg, lon + deg),
            )
        ).all()


class CacheRepository:
    """Repository for generic cache operations."""

    def __init__(self, db: Session):
        self.db = db

    def get(self, key: str) -> Optional[str]:
        """Get cache value."""
        entry = self.db.query(CacheEntryModel).filter(
            and_(
                CacheEntryModel.key == key,
                or_(
                    CacheEntryModel.expires_at.is_(None),
                    CacheEntryModel.expires_at > datetime.utcnow()
                )
            )
        ).first()
        return entry.value if entry else None

    def set(self, key: str, value: str, ttl_seconds: Optional[int] = None) -> None:
        """Set cache value."""
        expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds) if ttl_seconds else None
        entry = CacheEntryModel(key=key, value=value, expires_at=expires_at)
        self.db.merge(entry)

    def delete(self, key: str) -> bool:
        """Delete cache entry."""
        entry = self.db.query(CacheEntryModel).filter(CacheEntryModel.key == key).first()
        if entry:
            self.db.delete(entry)
            return True
        return False

    def cleanup_expired(self) -> int:
        """Remove expired cache entries."""
        result = self.db.query(CacheEntryModel).filter(
            and_(
                CacheEntryModel.expires_at.is_not(None),
                CacheEntryModel.expires_at < datetime.utcnow()
            )
        ).delete()
        return result


class GeocoderCacheRepository:
    """Repository for geocoder result cache."""

    def __init__(self, db: Session):
        self.db = db

    def get(self, query_hash: str) -> Optional[GeocoderCacheModel]:
        """Get cached geocoder result."""
        return self.db.query(GeocoderCacheModel).filter(
            and_(
                GeocoderCacheModel.query_hash == query_hash,
                or_(
                    GeocoderCacheModel.expires_at.is_(None),
                    GeocoderCacheModel.expires_at > datetime.utcnow()
                )
            )
        ).first()

    def set(self, query_hash: str, value: str, ttl_seconds: int = 86400) -> None:
        """Cache geocoder result with simple key-value."""
        expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        entry = GeocoderCacheModel(
            query_hash=query_hash,
            query_text="",  # Not used in simple mode
            provider="",     # Not used in simple mode
            latitude=0.0,
            longitude=0.0,
            confidence=None,
            raw_response=value,
            expires_at=expires_at,
        )
        self.db.merge(entry)


class EmbeddingCacheRepository:
    """Repository for embedding cache."""

    def __init__(self, db: Session):
        self.db = db

    def get(self, text_hash: str, model_name: str) -> Optional[list[float]]:
        """Get cached embedding."""
        entry = self.db.query(EmbeddingCacheModel).filter(
            and_(
                EmbeddingCacheModel.text_hash == text_hash,
                EmbeddingCacheModel.model_name == model_name
            )
        ).first()
        if entry:
            return json.loads(entry.embedding)
        return None

    def set(self, text_hash: str, text: str, model_name: str, embedding: list[float]) -> None:
        """Cache embedding."""
        entry = EmbeddingCacheModel(
            text_hash=text_hash,
            text=text,
            model_name=model_name,
            embedding=json.dumps(embedding),
        )
        self.db.merge(entry)