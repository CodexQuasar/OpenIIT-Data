"""SQLAlchemy database models."""

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, String, Float, DateTime, Integer, Text, Index, ForeignKey, Enum as SQLEnum
)
from sqlalchemy.orm import declarative_base, relationship

from app.schemas import VisitOutcome, CandidateSource, RecommendedAction

Base = declarative_base()


class AccountModel(Base):
    """Account database model."""

    __tablename__ = "accounts"

    account_id = Column(String(64), primary_key=True, index=True)
    address = Column(Text, nullable=False)
    normalized_address = Column(Text, nullable=True)
    language = Column(String(16), nullable=True)
    pincode = Column(String(16), nullable=True, index=True)
    locality = Column(String(128), nullable=True, index=True)
    city = Column(String(128), nullable=True, index=True)
    state = Column(String(128), nullable=True, index=True)
    town_id = Column(String(64), nullable=True, index=True)
    place_cluster_id = Column(String(64), nullable=True, index=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    confidence_radius_m = Column(Float, nullable=True)
    location_source = Column(String(32), nullable=True)
    location_crs = Column(String(32), nullable=True, default="WGS84")
    predicted_latitude = Column(Float, nullable=True)
    predicted_longitude = Column(Float, nullable=True)
    predicted_radius_m = Column(Float, nullable=True)
    predicted_at = Column(DateTime, nullable=True)
    confirmed_latitude = Column(Float, nullable=True)
    confirmed_longitude = Column(Float, nullable=True)
    confirmed_radius_m = Column(Float, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    location_updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    visits = relationship("VisitModel", back_populates="account", lazy="dynamic")
    predictions = relationship("PredictionModel", back_populates="account", lazy="dynamic")

    __table_args__ = (
        Index("ix_accounts_location", "latitude", "longitude"),
        Index("ix_accounts_pincode_locality", "pincode", "locality"),
        Index("ix_accounts_town", "town_id"),
    )


class VisitModel(Base):
    """Visit database model."""

    __tablename__ = "visits"

    visit_id = Column(String(64), primary_key=True, index=True)
    account_id = Column(String(64), ForeignKey("accounts.account_id"), nullable=False, index=True)
    agent_id = Column(String(64), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    gps_accuracy = Column(Float, nullable=True)
    outcome = Column(SQLEnum(VisitOutcome), nullable=False)
    dwell_time = Column(Integer, nullable=True)
    remarks = Column(Text, nullable=True)
    trajectory = Column(Text, nullable=True)  # JSON serialized
    integrity_score = Column(Float, nullable=True)
    reliability_score = Column(Float, nullable=True)
    remark_correction = Column(Text, nullable=True)
    coordinate_crs = Column(String(32), nullable=False, default="WGS84")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    account = relationship("AccountModel", back_populates="visits")

    __table_args__ = (
        Index("ix_visits_account_timestamp", "account_id", "timestamp"),
        Index("ix_visits_agent_timestamp", "agent_id", "timestamp"),
        Index("ix_visits_location", "latitude", "longitude"),
        Index("ix_visits_outcome", "outcome"),
    )


class PredictionModel(Base):
    """Prediction database model."""

    __tablename__ = "predictions"

    prediction_id = Column(String(64), primary_key=True, index=True)
    account_id = Column(String(64), ForeignKey("accounts.account_id"), nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    confidence_radius_m = Column(Float, nullable=False)
    prediction_method = Column(String(64), nullable=False)
    recommended_action = Column(SQLEnum(RecommendedAction), nullable=False)
    directions = Column(Text, nullable=True)
    evidence = Column(Text, nullable=True)  # JSON serialized
    model_version = Column(String(64), nullable=False)
    feature_version = Column(String(32), nullable=False)
    candidates = Column(Text, nullable=True)  # JSON serialized
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    account = relationship("AccountModel", back_populates="predictions")

    __table_args__ = (
        Index("ix_predictions_account_timestamp", "account_id", "timestamp"),
    )


class PlaceClusterModel(Base):
    """Place cluster database model."""

    __tablename__ = "place_clusters"

    cluster_id = Column(String(64), primary_key=True, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    account_ids = Column(Text, nullable=False)  # JSON serialized
    landmarks = Column(Text, nullable=True)  # JSON serialized
    address_variants = Column(Text, nullable=True)  # JSON serialized
    visit_count = Column(Integer, default=0)
    confidence = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_place_clusters_location", "latitude", "longitude"),
    )


class CacheEntryModel(Base):
    """Generic cache entry model."""

    __tablename__ = "cache_entries"

    key = Column(String(256), primary_key=True)
    value = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_cache_expires", "expires_at"),
    )


class GeocoderCacheModel(Base):
    """Geocoder result cache."""

    __tablename__ = "geocoder_cache"

    query_hash = Column(String(64), primary_key=True)
    query_text = Column(Text, nullable=False)
    provider = Column(String(32), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    confidence = Column(Float, nullable=True)
    raw_response = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index("ix_geocoder_cache_expires", "expires_at"),
    )


class EmbeddingCacheModel(Base):
    """Embedding cache."""

    __tablename__ = "embedding_cache"

    text_hash = Column(String(64), primary_key=True)
    text = Column(Text, nullable=False)
    model_name = Column(String(128), nullable=False)
    embedding = Column(Text, nullable=False)  # JSON serialized
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)