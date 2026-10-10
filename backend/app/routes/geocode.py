"""Geocoding routes."""

import os
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import uuid4

from data.database import get_db
from data.repositories import (
    AccountRepository, VisitRepository, PredictionRepository, PlaceClusterRepository
)
from app.schemas import (
    GeocodeRequest, GeocodeBatchRequest, Prediction,
    PredictionEvidence, CandidateLocation, CandidateSource,
    RecommendedAction, Account, VisitOutcome
)
from ml.address_normalizer import normalize_address
from ml.entity_extractor import extract_entities
from geospatial.candidate_generator import generate_candidates, CandidateGenerationContext
from geospatial.geocoder import geocode_address
from geospatial.directions import generate_directions, generate_field_directions
from ml.ranker import rank_candidates, CandidateRanker
from ml.calibration import ConfidenceCalibrator, recommend_action, SpatialUncertaintyEstimator
from ml.visit_evidence import score_visit
from ml.visit_integrity import detect_integrity
from ml.place_resolution import resolve_places, PlaceResolver
from config.settings import get_settings
from data.database import db_session
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/geocode", response_model=Prediction)
async def geocode_single(
    request: GeocodeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Geocode a single address."""
    account_repo = AccountRepository(db)
    visit_repo = VisitRepository(db)
    prediction_repo = PredictionRepository(db)
    cluster_repo = PlaceClusterRepository(db)
    
    # Get or create account
    account = None
    if request.account_id:
        account = account_repo.get_by_id(request.account_id)
    
    if not account:
        # Create temporary account for geocoding
        account = Account(
            account_id=request.account_id or f"temp_{uuid4().hex[:8]}",
            address=request.address,
            language=request.language,
            pincode=request.pincode,
            locality=request.locality,
            city=request.city,
            state=request.state,
        )
    
    # Normalize and extract entities
    normalized = extract_entities(request.address)
    
    # Get historical visits for this account
    historical_visits = []
    if account.account_id and not account.account_id.startswith("temp_"):
        historical_visits = visit_repo.get_by_account(account.account_id)
    
    # Get nearby accounts using spatial query (within 1km) if account has location
    nearby_accounts = []
    if account.latitude is not None and account.longitude is not None:
        nearby_accounts = account_repo.get_nearby_accounts(
            account.latitude, account.longitude, radius_m=1000, limit=20
        )
        # Exclude the account itself
        nearby_accounts = [a for a in nearby_accounts if a.account_id != account.account_id]
    
    # For new accounts without coordinates, discover related accounts via address entities
    # (landmarks, locality, pincode) to enable cross-account learning before first visit
    if not nearby_accounts and (normalized.landmark or normalized.locality or normalized.pincode):
        nearby_accounts = _discover_related_accounts(account_repo, normalized, account.account_id)
    
    # Get place clusters - use spatial query if account has location
    place_clusters = []
    if account.latitude is not None and account.longitude is not None:
        place_clusters = cluster_repo.get_nearby(account.latitude, account.longitude, radius_m=1000)
    
    # For new accounts without coordinates, find clusters via address entities
    if not place_clusters and (normalized.landmark or normalized.locality or normalized.pincode):
        place_clusters = _discover_place_clusters(cluster_repo, normalized)
    
    # Get geocoder results
    geocoder_results = []
    try:
        geocoder_results = await geocode_address(request.address, request.use_cache)
    except Exception as e:
        logger.warning(f"Geocoder failed: {e}")
        geocoder_results = []
    
    # Generate candidates - disable dataset lookups in production for performance
    candidate_config = {"disable_dataset_lookups": os.environ.get("TESTING") == "1" or os.environ.get("DISABLE_DATASET_LOOKUPS") == "1"}
    candidates = generate_candidates(
        normalized,
        historical_visits,
        nearby_accounts,
        place_clusters,
        geocoder_results,
        candidate_config,
    )
    
    if not candidates:
        # No candidates found - return unresolved status with explicit action
        return Prediction(
            account_id=account.account_id,
            latitude=None,
            longitude=None,
            confidence=0.0,
            confidence_radius_m=None,
            prediction_method="no_candidates",
            recommended_action=RecommendedAction.VERIFY_FIRST,
            directions="Address could not be geocoded. Manual verification required.",
            evidence=PredictionEvidence(
                strongest_evidence=["No candidate locations found"],
                historical_visits=0,
                reliable_visits=0,
                nearby_accounts=0,
                geocoder_support=False,
                main_landmark=normalized.landmark,
            ),
            model_version=get_settings().model_version,
            feature_version=get_settings().feature_version,
        )
    
    # Rank candidates
    ranker = CandidateRanker()
    ranked = rank_candidates(candidates, normalized, historical_visits, nearby_accounts, place_clusters, ranker)
    
    # Best candidate
    best = ranked[0]
    
    # Score visit reliabilities
    visit_reliabilities = []
    for visit in historical_visits:
        if visit.outcome in [VisitOutcome.SUCCESSFUL_CONTACT, VisitOutcome.PARTIAL_CONTACT]:
            reliability = score_visit(visit, historical_visits)
            visit_reliabilities.append(reliability.score)
    
    # Estimate confidence and radius
    uncertainty = SpatialUncertaintyEstimator()
    confidence, radius = uncertainty.estimate(best, ranked, visit_reliabilities)
    
    # Calibrate confidence
    calibrator = ConfidenceCalibrator()
    calibrated_confidence = calibrator.calibrate_confidence(confidence)
    
    # Recommended action
    action = recommend_action(calibrated_confidence, radius)
    
    # Generate directions
    directions = generate_directions(normalized, best)
    
    # Build evidence
    evidence = PredictionEvidence(
        historical_visits=len(historical_visits),
        reliable_visits=sum(1 for r in visit_reliabilities if r > 0.5),
        nearby_accounts=len(nearby_accounts),
        geocoder_support=len(geocoder_results) > 0,
        main_landmark=normalized.landmark,
        strongest_evidence=_build_evidence_strings(best, historical_visits, nearby_accounts),
    )
    
    # Create prediction
    prediction = Prediction(
        account_id=account.account_id,
        latitude=best.latitude,
        longitude=best.longitude,
        confidence=calibrated_confidence,
        confidence_radius_m=radius,
        prediction_method="candidate_ranking",
        recommended_action=action,
        directions=directions,
        evidence=evidence,
        model_version=get_settings().model_version,
        feature_version=get_settings().feature_version,
        candidates=ranked[:5],  # Top 5 for debugging
    )
    
    # Save prediction and update account location if account exists
    if account.account_id and not account.account_id.startswith("temp_"):
        background_tasks.add_task(prediction_repo.create, prediction)
        # Update account location with the prediction
        background_tasks.add_task(
            _update_account_location,
            account.account_id,
            best.latitude,
            best.longitude,
            calibrated_confidence,
            radius,
        )
    
    return prediction


async def _update_account_location(
    account_id: str,
    latitude: float,
    longitude: float,
    confidence: float,
    confidence_radius_m: float,
):
    """Background task to update account location."""
    try:
        with db_session() as db:
            account_repo = AccountRepository(db)
            # Use repository method for consistent updates
            if confidence >= 0.5:
                account_repo.update_location(
                    account_id, latitude, longitude,
                    confidence, confidence_radius_m,
                    source="prediction"
                )
                db.commit()
                logger.info(f"Updated account {account_id} location: {latitude}, {longitude} (conf={confidence:.2f})")
    except Exception as e:
        logger.error(f"Failed to update account location: {e}")


@router.post("/geocode/batch", response_model=List[Prediction])
async def geocode_batch(
    request: GeocodeBatchRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Batch geocode multiple addresses."""
    predictions = []
    
    for account_request in request.accounts:
        single_request = GeocodeRequest(
            account_id=account_request.account_id,
            address=account_request.address,
            language=account_request.language,
            pincode=account_request.pincode,
            locality=account_request.locality,
            city=account_request.city,
            state=account_request.state,
            use_cache=account_request.use_cache,
        )
        pred = await geocode_single(single_request, background_tasks, db)
        predictions.append(pred)
    
    return predictions


def _build_evidence_strings(
    candidate: CandidateLocation,
    visits: list,
    accounts: list
) -> list[str]:
    """Build human-readable evidence strings."""
    evidence = []
    
    if candidate.supporting_visit_count > 0:
        evidence.append(
            f"{candidate.supporting_visit_count} successful visits within "
            f"{candidate.gps_accuracy or 0:.0f}m"
        )
    
    if candidate.nearby_account_support > 0:
        evidence.append(
            f"{candidate.nearby_account_support} nearby accounts confirm the location"
        )
    
    if candidate.commercial_geocoder_distance is not None and candidate.commercial_geocoder_distance < 1000:
        evidence.append(
            f"Commercial geocoder was {candidate.commercial_geocoder_distance:.0f}m away"
        )
    
    if candidate.place_cluster_support > 0:
        evidence.append(
            f"Place cluster with {candidate.place_cluster_support} accounts supports this location"
        )
    
    if not evidence:
        evidence.append("Limited evidence available")
    
    return evidence


def _discover_related_accounts(
    account_repo: AccountRepository,
    normalized,
    exclude_account_id: str = None
) -> list:
    """
    Discover related accounts via address entities (landmarks, locality, pincode)
    for cross-account learning before an account has coordinates.
    """
    related = []
    
    # Search by landmark
    if normalized.landmark:
        landmark_accounts = account_repo.search(normalized.landmark, limit=10)
        related.extend(landmark_accounts)
    
    # Search by locality
    if normalized.locality:
        locality_accounts = account_repo.search(normalized.locality, limit=10)
        related.extend(locality_accounts)
    
    # Search by pincode
    if normalized.pincode:
        pincode_accounts = account_repo.search(normalized.pincode, limit=10)
        related.extend(pincode_accounts)
    
    # Deduplicate and exclude self
    seen = set()
    deduped = []
    for acc in related:
        if acc.account_id == exclude_account_id:
            continue
        if acc.account_id not in seen:
            seen.add(acc.account_id)
            deduped.append(acc)
    
    return deduped[:20]


def _discover_place_clusters(
    cluster_repo: PlaceClusterRepository,
    normalized
) -> list:
    """
    Discover place clusters via address entities (landmarks, locality, pincode)
    for cross-account learning before an account has coordinates.
    """
    clusters = []
    
    # Search clusters by landmark
    if normalized.landmark:
        # Would need cluster search by landmark - for now use nearby search
        pass
    
    # Search clusters by locality
    if normalized.locality:
        pass
    
    return clusters