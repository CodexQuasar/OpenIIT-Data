"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=(),
    )

    # Environment
    environment: str = Field(default="development", alias="ENVIRONMENT")

    # Security / Auth
    secret_key: str = Field(default="change-me-in-production-9f8e7d6c", alias="SECRET_KEY")
    token_ttl_hours: int = Field(default=12, alias="TOKEN_TTL_HOURS")

    # Compliance
    dpdp_retention_days: int = Field(default=2555, alias="DPDP_RETENTION_DAYS")
    rbi_contact_window_start: str = Field(default="07:00", alias="RBI_CONTACT_WINDOW_START")
    rbi_contact_window_end: str = Field(default="20:00", alias="RBI_CONTACT_WINDOW_END")
    rbi_max_contacts_per_day: int = Field(default=3, alias="RBI_MAX_CONTACTS_PER_DAY")
    rbi_max_contacts_per_week: int = Field(default=7, alias="RBI_MAX_CONTACTS_PER_WEEK")

    # Database
    database_url: str = Field(
        default="sqlite:///./data/geocoder.db", alias="DATABASE_URL"
    )

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # External Geocoder
    nominatim_user_agent: str = Field(
        default="OpenIIT-Geocoder/1.0", alias="NOMINATIM_USER_AGENT"
    )
    google_maps_api_key: Optional[str] = Field(
        default=None, alias="GOOGLE_MAPS_API_KEY"
    )

    # ML Models
    embedding_model: str = Field(
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        alias="EMBEDDING_MODEL",
    )
    use_cuda: bool = Field(default=False, alias="USE_CUDA")

    # API
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173", alias="CORS_ORIGINS"
    )

    # Geocoding Pipeline
    candidate_count: int = Field(default=20, alias="CANDIDATE_COUNT")
    max_candidates_per_source: int = Field(default=10, alias="MAX_CANDIDATES_PER_SOURCE")
    deduplication_radius_m: float = Field(default=50.0, alias="DEDUPLICATION_RADIUS_M")

    # Visit Evidence
    min_gps_accuracy_m: float = Field(default=5.0, alias="MIN_GPS_ACCURACY_M")
    max_gps_accuracy_m: float = Field(default=500.0, alias="MAX_GPS_ACCURACY_M")
    min_dwell_time_seconds: int = Field(default=30, alias="MIN_DWELL_TIME_SECONDS")
    max_dwell_time_seconds: int = Field(default=3600, alias="MAX_DWELL_TIME_SECONDS")

    # Integrity Detection
    integrity_same_coord_threshold: int = Field(default=3, alias="INTEGRITY_SAME_COORD_THRESHOLD")
    integrity_speed_threshold_kmh: float = Field(default=80.0, alias="INTEGRITY_SPEED_THRESHOLD_KMH")
    integrity_min_visit_duration_seconds: int = Field(default=10, alias="INTEGRITY_MIN_VISIT_DURATION_SECONDS")

    # Agent Bias Control
    max_agent_contribution_weight: float = Field(default=0.4, alias="MAX_AGENT_CONTRIBUTION_WEIGHT")
    min_independent_agents_for_high_confidence: int = Field(default=2, alias="MIN_INDEPENDENT_AGENTS_FOR_HIGH_CONFIDENCE")

    # Place Clustering
    place_cluster_eps_m: float = Field(default=100.0, alias="PLACE_CLUSTER_EPS_M")
    place_cluster_min_samples: int = Field(default=2, alias="PLACE_CLUSTER_MIN_SAMPLES")
    text_similarity_threshold: float = Field(default=0.75, alias="TEXT_SIMILARITY_THRESHOLD")

    # Ranking Model
    ranking_model_path: str = Field(default="models/ranker.txt", alias="RANKING_MODEL_PATH")
    feature_version: str = Field(default="v1", alias="FEATURE_VERSION")
    model_version: str = Field(default="geocoder-v1.0", alias="MODEL_VERSION")

    # Confidence Calibration
    calibration_method: str = Field(default="isotonic", alias="CALIBRATION_METHOD")
    calibration_model_path: str = Field(default="models/calibrator.joblib", alias="CALIBRATION_MODEL_PATH")
    confidence_threshold_direct: float = Field(default=0.85, alias="CONFIDENCE_THRESHOLD_DIRECT")
    confidence_threshold_verify: float = Field(default=0.60, alias="CONFIDENCE_THRESHOLD_VERIFY")
    direct_visit_radius_m: float = Field(default=100.0, alias="DIRECT_VISIT_RADIUS_M")
    verification_radius_m: float = Field(default=500.0, alias="VERIFICATION_RADIUS_M")

    # Caching
    cache_ttl_seconds: int = Field(default=86400, alias="CACHE_TTL_SECONDS")
    embedding_cache_size: int = Field(default=10000, alias="EMBEDDING_CACHE_SIZE")

    # Batch Processing
    batch_size: int = Field(default=100, alias="BATCH_SIZE")
    max_workers: int = Field(default=4, alias="MAX_WORKERS")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()