"""Visit routes."""
import os
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List
from uuid import uuid4
from datetime import datetime

from data.database import get_db
from data.repositories import VisitRepository, AccountRepository, PredictionRepository, PlaceClusterRepository
from app.schemas import (
    Visit, VisitCreateRequest, VisitValidateRequest, VisitOutcome,
    TrajectoryPoint, GeocodeRequest, Prediction, CandidateLocation,
    PredictionEvidence
)
from ml.visit_evidence import score_visit, ReliabilityScore
from ml.visit_integrity import detect_integrity, IntegrityScore
from geospatial.candidate_generator import generate_candidates
from geospatial.geocoder import geocode_address
from ml.ranker import rank_candidates, CandidateRanker
from ml.calibration import ConfidenceCalibrator, recommend_action, SpatialUncertaintyEstimator
from ml.address_normalizer import normalize_address
from ml.entity_extractor import extract_entities
from data.database import db_session
import logging
import re

logger = logging.getLogger(__name__)

router = APIRouter()


def _extract_remark_correction(remarks: str | None) -> str | None:
    """Keep an auditable correction phrase without pretending to geocode it."""
    if not remarks:
        return None
    match = re.search(
        r"(?:actual|house|ghar|address|location).{0,80}(?:gali|lane|street|aage|behind|near|opposite).{0,80}",
        remarks,
        re.IGNORECASE,
    )
    return match.group(0).strip() if match else None


@router.post("/visits/validate", response_model=dict)
async def validate_visit(
    request: VisitValidateRequest,
    db: Session = Depends(get_db),
):
    """Validate a visit request and return reliability/integrity scores."""
    visit_request = request.visit  # The VisitCreateRequest nested inside
    visit_repo = VisitRepository(db)
    # Create a temporary visit object for validation
    from app.schemas import VisitOutcome
    visit = Visit(
        visit_id=f"visit_{uuid4().hex[:12]}",
        account_id=visit_request.account_id,
        agent_id=visit_request.agent_id,
        timestamp=visit_request.timestamp,
        latitude=visit_request.latitude,
        longitude=visit_request.longitude,
        gps_accuracy=visit_request.gps_accuracy,
        outcome=VisitOutcome(visit_request.outcome),
        dwell_time=visit_request.dwell_time,
        remarks=visit_request.remarks,
        trajectory=visit_request.trajectory,
    )
    
    historical_visits = visit_repo.get_by_account(visit_request.account_id)
    all_visits = historical_visits + [visit]
    
    from ml.visit_evidence import score_visit
    from ml.visit_integrity import detect_integrity
    
    reliability = score_visit(visit, historical_visits)
    integrity = detect_integrity(visit, all_visits)
    
    return {
        "score": reliability.score,
        "risk_level": integrity.risk_level,
        "integrity_score": integrity.score,
    }


@router.post("/visits", response_model=Visit, status_code=status.HTTP_201_CREATED)
async def create_visit(
    request: VisitCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Create a new visit record."""
    visit_repo = VisitRepository(db)
    account_repo = AccountRepository(db)
    
    # Verify account exists
    account = account_repo.get_by_id(request.account_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {request.account_id} not found"
        )
    
    # Create visit
    visit = Visit(
        visit_id=f"visit_{uuid4().hex[:12]}",
        account_id=request.account_id,
        agent_id=request.agent_id,
        timestamp=request.timestamp,
        latitude=request.latitude,
        longitude=request.longitude,
        gps_accuracy=request.gps_accuracy,
        outcome=request.outcome,
        dwell_time=request.dwell_time,
        remarks=request.remarks,
        trajectory=request.trajectory,
        remark_correction=_extract_remark_correction(request.remarks),
        coordinate_crs="WGS84",
    )
    
    # Calculate reliability and integrity scores
    historical_visits = visit_repo.get_by_account(request.account_id)
    all_visits = historical_visits + [visit]
    
    reliability = score_visit(visit, historical_visits)
    visit.reliability_score = reliability.score
    
    integrity = detect_integrity(visit, all_visits)
    visit.integrity_score = integrity.score
    
    # Save
    visit_repo.create(visit)
    db.commit()
    
    # Trigger background tasks for continuous improvement
    background_tasks.add_task(_refresh_account_prediction, request.account_id)
    background_tasks.add_task(_update_place_clusters, request.account_id, visit)
    
    return visit


async def _refresh_account_prediction(account_id: str):
    """Background task to recompute account prediction after a new visit."""
    try:
        with db_session() as db:
            account_repo = AccountRepository(db)
            visit_repo = VisitRepository(db)
            prediction_repo = PredictionRepository(db)
            cluster_repo = PlaceClusterRepository(db)
            
            account = account_repo.get_by_id(account_id)
            if not account:
                return
            
            # Get historical visits
            historical_visits = visit_repo.get_by_account(account_id)
            
            # Get nearby accounts
            nearby_accounts = []
            if account.latitude is not None and account.longitude is not None:
                nearby_accounts = account_repo.get_nearby_accounts(
                    account.latitude, account.longitude, radius_m=1000, limit=20
                )
                nearby_accounts = [a for a in nearby_accounts if a.account_id != account_id]
            
            # Get place clusters - use spatial query if account has location
            place_clusters = []
            if account.latitude is not None and account.longitude is not None:
                place_clusters = cluster_repo.get_nearby(account.latitude, account.longitude, radius_m=1000)
            
            # Normalize address
            normalized = extract_entities(account.address)
            
            # Get geocoder results
            geocoder_results = []
            try:
                geocoder_results = await geocode_address(account.address, use_cache=True)
            except Exception as e:
                logger.warning(f"Geocoder failed during refresh: {e}")
            
            # Generate and rank candidates
            candidate_config = {"disable_dataset_lookups": os.environ.get("TESTING") == "1"}
            candidates = generate_candidates(
                normalized,
                historical_visits,
                nearby_accounts,
                place_clusters,
                geocoder_results,
                candidate_config,
            )
            
            if candidates:
                ranker = CandidateRanker()
                ranked = rank_candidates(candidates, normalized, historical_visits, nearby_accounts, place_clusters, ranker)
                best = ranked[0]
                
                # Score visit reliabilities
                visit_reliabilities = []
                for v in historical_visits:
                    if v.outcome in [VisitOutcome.SUCCESSFUL_CONTACT, VisitOutcome.PARTIAL_CONTACT]:
                        reliability = score_visit(v, historical_visits)
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
                    account_id=account_id,
                    latitude=best.latitude,
                    longitude=best.longitude,
                    confidence=calibrated_confidence,
                    confidence_radius_m=radius,
                    prediction_method="candidate_ranking",
                    recommended_action=action,
                    directions=directions,
                    evidence=evidence,
                    model_version="1.0.0",
                    feature_version="1.0.0",
                    candidates=ranked[:5],
                )
                
                # Save prediction
                prediction_repo.create(prediction)
                db.commit()
                
                # Update account location if confidence is high enough
                if calibrated_confidence >= 0.5:
                    account_repo.update_location(
                        account_id, best.latitude, best.longitude,
                        calibrated_confidence, radius,
                        source="prediction"
                    )
                    db.commit()
                logger.info(f"Refreshed prediction for account {account_id}: {best.latitude}, {best.longitude} (conf={calibrated_confidence:.2f})")
    except Exception as e:
        logger.error(f"Failed to refresh prediction for account {account_id}: {e}")


async def _update_place_clusters(account_id: str, visit: Visit):
    """Background task to update place clusters after a successful visit."""
    try:
        with db_session() as db:
            account_repo = AccountRepository(db)
            cluster_repo = PlaceClusterRepository(db)
            
            account = account_repo.get_by_id(account_id)
            if not account:
                return
            
            # Only update clusters for successful visits
            if visit.outcome not in [VisitOutcome.SUCCESSFUL_CONTACT, VisitOutcome.PARTIAL_CONTACT]:
                return
            
            # Check if there's an existing cluster nearby
            nearby_clusters = cluster_repo.get_nearby(visit.latitude, visit.longitude, radius_m=100)
            
            if nearby_clusters:
                # Add account to existing cluster
                cluster = nearby_clusters[0]
                # Update cluster with new account
                import json
                account_ids = json.loads(cluster.account_ids) if cluster.account_ids else []
                if account_id not in account_ids:
                    account_ids.append(account_id)
                    cluster.account_ids = json.dumps(account_ids)
                cluster.visit_count = len(account_ids)
                # Update confidence based on number of accounts
                cluster.confidence = min(1.0, 0.5 + len(account_ids) * 0.1)
                # A successful visit is stronger evidence than a prediction.
                account_repo.update_location(
                    account_id,
                    visit.latitude,
                    visit.longitude,
                    visit.reliability_score or 0.5,
                    visit.gps_accuracy or 50.0,
                    cluster_id=cluster.cluster_id,
                    source="visit_confirmed",
                )
                for related_account_id in account_ids:
                    if related_account_id != account_id:
                        related = account_repo.get_by_id(related_account_id)
                        if related and (related.location_source != "visit_confirmed" or
                                        (related.confidence or 0) < (visit.reliability_score or 0.5)):
                            account_repo.update_location(
                                related_account_id,
                                visit.latitude,
                                visit.longitude,
                                visit.reliability_score or 0.5,
                                visit.gps_accuracy or 50.0,
                                cluster_id=cluster.cluster_id,
                                source="cluster_confirmed",
                            )
                cluster.updated_at = datetime.utcnow()
                db.commit()
                logger.info(f"Added account {account_id} to existing cluster {cluster.cluster_id}")
            else:
                # Create new cluster for this location
                import uuid
                new_cluster_id = f"cluster_{uuid.uuid4().hex[:12]}"
                cluster = cluster_repo.create(PlaceCluster(
                    cluster_id=new_cluster_id,
                    latitude=visit.latitude,
                    longitude=visit.longitude,
                    account_ids=[account_id],
                    landmarks=[],
                    address_variants=[],
                    visit_count=1,
                    confidence=0.5,
                ))
                # Link account to cluster
                account_repo.update_location(
                    account_id, visit.latitude, visit.longitude,
                    visit.reliability_score or 0.5, 50.0, 
                    cluster_id=new_cluster_id,
                    source="visit_confirmed"
                )
                db.commit()
                logger.info(f"Created new cluster {new_cluster_id} for account {account_id}")
    except Exception as e:
        logger.error(f"Failed to update place clusters for account {account_id}: {e}")