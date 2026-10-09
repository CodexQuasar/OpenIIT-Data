"""Pydantic schemas for data models."""

import json
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing_extensions import Annotated


class VisitOutcome(str, Enum):
    """Possible visit outcomes."""

    SUCCESSFUL_CONTACT = "SUCCESSFUL_CONTACT"
    PARTIAL_CONTACT = "PARTIAL_CONTACT"
    FAILED_SEARCH = "FAILED_SEARCH"
    ADDRESS_NOT_TRACEABLE = "ADDRESS_NOT_TRACEABLE"
    WRONG_ADDRESS = "WRONG_ADDRESS"
    BORROWER_MOVED = "BORROWER_MOVED"
    OTHER = "OTHER"


class CandidateSource(str, Enum):
    """Source of a candidate location."""

    HISTORICAL_VISIT = "HISTORICAL_VISIT"
    NEARBY_ACCOUNT = "NEARBY_ACCOUNT"
    GEOCODER = "GEOCODER"
    LANDMARK = "LANDMARK"
    LOCALITY = "LOCALITY"
    PINCODE = "PINCODE"
    INTERPOLATION = "INTERPOLATION"


class RecommendedAction(str, Enum):
    """Recommended action based on confidence."""

    VISIT_DIRECTLY = "VISIT_DIRECTLY"
    VERIFY_FIRST = "VERIFY_FIRST"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


class RelationType(str, Enum):
    """Spatial relation types."""

    BEHIND = "BEHIND"
    NEAR = "NEAR"
    OPPOSITE = "OPPOSITE"
    NEXT_TO = "NEXT_TO"
    AFTER = "AFTER"
    BEFORE = "BEFORE"
    BETWEEN = "BETWEEN"
    AROUND = "AROUND"
    INSIDE = "INSIDE"
    OUTSIDE = "OUTSIDE"
    CORNER = "CORNER"
    ENTRANCE = "ENTRANCE"
    BACKSIDE = "BACKSIDE"
    FRONT = "FRONT"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"
    WEST = "WEST"


class AddressEntity(BaseModel):
    """Extracted address entity."""

    model_config = ConfigDict(use_enum_values=True)

    entity_type: str = Field(..., description="Type of entity (HOUSE_NUMBER, BUILDING, LANDMARK, etc.)")
    value: str = Field(..., description="Extracted value")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Extraction confidence")
    relation: Optional[RelationType] = Field(default=None, description="Spatial relation to another entity")
    secondary_entity: Optional[str] = Field(default=None, description="Secondary entity in relation")


class NormalizedAddress(BaseModel):
    """Normalized address with entities."""

    raw_address: str = Field(..., description="Original raw address")
    normalized_address: str = Field(..., description="Normalized address")
    language: Optional[str] = Field(default=None, description="Detected language")
    entities: list[AddressEntity] = Field(default_factory=list, description="Extracted entities")
    pincode: Optional[str] = Field(default=None, description="Extracted pincode")
    locality: Optional[str] = Field(default=None, description="Extracted locality")
    city: Optional[str] = Field(default=None, description="Extracted city")
    state: Optional[str] = Field(default=None, description="Extracted state")
    landmark: Optional[str] = Field(default=None, description="Primary landmark")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Overall normalization confidence")


class Account(BaseModel):
    """Borrower account."""

    model_config = ConfigDict(from_attributes=True)

    account_id: str = Field(..., description="Unique account identifier")
    address: str = Field(..., description="Raw borrower address")
    normalized_address: Optional[NormalizedAddress] = Field(default=None)
    language: Optional[str] = Field(default=None)
    pincode: Optional[str] = Field(default=None)
    locality: Optional[str] = Field(default=None)
    city: Optional[str] = Field(default=None)
    state: Optional[str] = Field(default=None)
    town_id: Optional[str] = Field(default=None, description="Town identifier for spatial queries")
    place_cluster_id: Optional[str] = Field(default=None)
    # Location prediction fields
    latitude: Optional[float] = Field(default=None, ge=-90, le=90, description="Predicted latitude")
    longitude: Optional[float] = Field(default=None, ge=-180, le=180, description="Predicted longitude")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Location prediction confidence")
    confidence_radius_m: Optional[float] = Field(default=None, ge=0, description="Confidence radius in meters")
    location_source: Optional[str] = Field(default=None, description="Source of location (prediction, visit, manual)")
    location_crs: str = Field(default="WGS84")
    confirmed_latitude: Optional[float] = None
    confirmed_longitude: Optional[float] = None
    confirmed_radius_m: Optional[float] = Field(default=None, ge=0)
    confirmed_at: Optional[datetime] = None
    predicted_latitude: Optional[float] = None
    predicted_longitude: Optional[float] = None
    predicted_radius_m: Optional[float] = Field(default=None, ge=0)
    predicted_at: Optional[datetime] = None
    location_updated_at: Optional[datetime] = Field(default=None, description="When location was last updated")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("normalized_address", mode="before")
    @classmethod
    def parse_normalized_address(cls, v):
        """Parse normalized_address from JSON string if needed."""
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return None
        return v


class GPSPoint(BaseModel):
    """Single GPS coordinate with metadata."""

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    accuracy: Optional[float] = Field(default=None, ge=0, description="GPS accuracy in meters")
    timestamp: Optional[datetime] = Field(default=None)
    speed: Optional[float] = Field(default=None, ge=0, description="Speed in m/s")


class TrajectoryPoint(BaseModel):
    """Point in a visit trajectory."""

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    timestamp: datetime
    accuracy: Optional[float] = Field(default=None, ge=0)
    speed: Optional[float] = Field(default=None, ge=0)


class Visit(BaseModel):
    """Field visit record."""

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    visit_id: str = Field(..., description="Unique visit identifier")
    account_id: str = Field(..., description="Account visited")
    agent_id: str = Field(..., description="Field agent identifier")
    timestamp: datetime = Field(..., description="Visit timestamp")
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    gps_accuracy: Optional[float] = Field(default=None, ge=0, description="GPS accuracy in meters")
    outcome: VisitOutcome = Field(..., description="Visit outcome")
    dwell_time: Optional[int] = Field(default=None, ge=0, description="Dwell time in seconds")
    remarks: Optional[str] = Field(default=None, description="Agent remarks")
    trajectory: list[TrajectoryPoint] = Field(default_factory=list, description="GPS trajectory points")
    integrity_score: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Visit integrity score")
    reliability_score: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Visit reliability score")
    remark_correction: Optional[str] = None
    coordinate_crs: str = "WGS84"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CandidateLocation(BaseModel):
    """Candidate location for geocoding."""

    model_config = ConfigDict(use_enum_values=True)

    candidate_id: str = Field(..., description="Unique candidate identifier")
    latitude: float = Field(..., description="X coordinate (local system) or latitude")
    longitude: float = Field(..., description="Y coordinate (local system) or longitude")
    source: CandidateSource = Field(..., description="Source of this candidate")
    source_reference: Optional[str] = Field(default=None, description="Reference ID (visit_id, account_id, etc.)")
    address_similarity: float = Field(default=0.0, ge=0.0, le=1.0)
    landmark_similarity: float = Field(default=0.0, ge=0.0, le=1.0)
    locality_similarity: float = Field(default=0.0, ge=0.0, le=1.0)
    distance_to_successful_visits: Optional[float] = Field(default=None, ge=0)
    distance_to_failed_visits: Optional[float] = Field(default=None, ge=0)
    supporting_visit_count: int = Field(default=0)
    weighted_successful_visit_count: float = Field(default=0.0)
    visit_integrity: float = Field(default=1.0, ge=0.0, le=1.0)
    gps_accuracy: Optional[float] = Field(default=None, ge=0)
    dwell_time: Optional[float] = Field(default=None, ge=0)
    trajectory_quality: float = Field(default=0.0, ge=0.0, le=1.0)
    nearby_account_support: int = Field(default=0)
    commercial_geocoder_distance: Optional[float] = Field(default=None, ge=0)
    place_cluster_support: int = Field(default=0)
    agent_independence: float = Field(default=1.0, ge=0.0, le=1.0)
    score: Optional[float] = Field(default=None, description="Final ranking score")
    probability: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Normalized probability")


class PredictionEvidence(BaseModel):
    """Evidence supporting a prediction."""

    historical_visits: int = Field(default=0)
    reliable_visits: int = Field(default=0)
    nearby_accounts: int = Field(default=0)
    geocoder_support: bool = Field(default=False)
    main_landmark: Optional[str] = Field(default=None)
    strongest_evidence: list[str] = Field(default_factory=list)
    visit_integrity_flags: list[str] = Field(default_factory=list)
    agent_bias_warnings: list[str] = Field(default_factory=list)


class Prediction(BaseModel):
    """Geocoding prediction result."""

    model_config = ConfigDict(use_enum_values=True, protected_namespaces=())

    account_id: str
    latitude: Optional[float] = Field(default=None, ge=-90, le=90, description="Predicted latitude, null if unresolved")
    longitude: Optional[float] = Field(default=None, ge=-180, le=180, description="Predicted longitude, null if unresolved")
    confidence: float = Field(..., ge=0.0, le=1.0)
    confidence_radius_m: Optional[float] = Field(default=None, ge=0, description="Confidence radius in meters, null if unresolved")
    prediction_method: str = Field(default="candidate_ranking")
    recommended_action: RecommendedAction
    directions: str = Field(default="")
    evidence: PredictionEvidence = Field(default_factory=PredictionEvidence)
    model_version: str
    feature_version: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    candidates: Optional[list[CandidateLocation]] = Field(default=None, description="Top candidates for debugging")


class GeocodeRequest(BaseModel):
    """Request for geocoding an address."""

    account_id: Optional[str] = Field(default=None)
    address: str = Field(..., min_length=1, max_length=1000)
    language: Optional[str] = Field(default=None)
    pincode: Optional[str] = Field(default=None)
    locality: Optional[str] = Field(default=None)
    city: Optional[str] = Field(default=None)
    state: Optional[str] = Field(default=None)
    use_cache: bool = Field(default=True)


class GeocodeBatchRequest(BaseModel):
    """Batch geocoding request."""

    accounts: list[GeocodeRequest] = Field(..., min_length=1, max_length=1000)
    use_cache: bool = Field(default=True)


class VisitCreateRequest(BaseModel):
    """Request to create a visit record."""

    account_id: str
    agent_id: str
    timestamp: datetime
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    gps_accuracy: Optional[float] = Field(default=None, ge=0)
    outcome: VisitOutcome
    dwell_time: Optional[int] = Field(default=None, ge=0)
    remarks: Optional[str] = Field(default=None)
    trajectory: list[TrajectoryPoint] = Field(default_factory=list)


class VisitValidateRequest(BaseModel):
    """Request to validate visit integrity."""

    visit: VisitCreateRequest
    check_historical: bool = Field(default=True)


class HealthResponse(BaseModel):
    """Health check response."""

    model_config = ConfigDict(protected_namespaces=())

    status: str = "healthy"
    version: str = "1.0.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    database: str = "connected"
    model_loaded: bool = False


class ModelInfo(BaseModel):
    """Model information."""

    model_config = ConfigDict(protected_namespaces=())

    model_name: str
    model_version: str
    feature_version: str
    embedding_model: str
    training_date: Optional[datetime] = None
    metrics: dict[str, float] = Field(default_factory=dict)
    ablation_results: dict[str, dict[str, float]] = Field(default_factory=dict)


class PlaceCluster(BaseModel):
    """Place cluster representing multiple accounts at same location."""

    cluster_id: str
    latitude: float
    longitude: float
    account_ids: list[str]
    landmarks: list[str]
    address_variants: list[str]
    visit_count: int
    confidence: float
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MetricsResponse(BaseModel):
    """System metrics."""

    total_accounts: int
    total_visits: int
    predictions_made: int
    high_confidence_rate: float
    median_error_m: Optional[float] = None
    p90_error_m: Optional[float] = None
    confidence_coverage: Optional[float] = None
    calibration_error: Optional[float] = None
    address_not_traceable_rate: float
    productive_visits: int
    within_50m: Optional[float] = None
    within_100m: Optional[float] = None
    within_250m: Optional[float] = None
    within_500m: Optional[float] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)