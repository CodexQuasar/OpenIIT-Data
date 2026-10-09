"""Account routes."""

import json
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from data.database import get_db
from data.repositories import AccountRepository, VisitRepository, PredictionRepository
from app.schemas import (
    Account, Prediction, PredictionEvidence, Visit, VisitOutcome
)
from ml.address_normalizer import normalize_address
from ml.entity_extractor import extract_entities


router = APIRouter()


def _deserialize_prediction(prediction):
    if prediction is None:
        return None
    evidence = prediction.evidence
    candidates = prediction.candidates
    return {
        "account_id": prediction.account_id,
        "latitude": prediction.latitude,
        "longitude": prediction.longitude,
        "confidence": prediction.confidence,
        "confidence_radius_m": prediction.confidence_radius_m,
        "prediction_method": prediction.prediction_method,
        "recommended_action": prediction.recommended_action,
        "directions": prediction.directions or "",
        "evidence": json.loads(evidence) if isinstance(evidence, str) else (evidence or {}),
        "model_version": prediction.model_version,
        "feature_version": prediction.feature_version,
        "timestamp": prediction.timestamp,
        "candidates": json.loads(candidates) if isinstance(candidates, str) else candidates,
    }


@router.post("/accounts", response_model=Account, status_code=status.HTTP_201_CREATED)
async def create_account(
    account: Account,
    db: Session = Depends(get_db),
):
    """Create a new account."""
    account_repo = AccountRepository(db)
    
    # Check if already exists
    existing = account_repo.get_by_id(account.account_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Account {account.account_id} already exists"
        )
    
    # Normalize address
    normalized = extract_entities(account.address)
    account.normalized_address = normalized
    account.language = normalized.language
    account.pincode = normalized.pincode
    account.locality = normalized.locality
    account.city = normalized.city
    account.state = normalized.state
    
    # Save
    account_repo.create(account)
    
    return account


@router.get("/accounts/{account_id}", response_model=Account)
async def get_account(
    account_id: str,
    db: Session = Depends(get_db),
):
    """Get account by ID."""
    account_repo = AccountRepository(db)
    account = account_repo.get_by_id(account_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {account_id} not found"
        )
    return account


@router.get("/accounts/{account_id}/evidence")
async def get_account_evidence(
    account_id: str,
    db: Session = Depends(get_db),
):
    """Get all evidence for an account."""
    account_repo = AccountRepository(db)
    visit_repo = VisitRepository(db)
    
    account = account_repo.get_by_id(account_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {account_id} not found"
        )
    
    visits = visit_repo.get_by_account(account_id)
    
    # Categorize visits
    successful = [v for v in visits if v.outcome in [VisitOutcome.SUCCESSFUL_CONTACT, VisitOutcome.PARTIAL_CONTACT]]
    failed = [v for v in visits if v.outcome in [VisitOutcome.FAILED_SEARCH, VisitOutcome.ADDRESS_NOT_TRACEABLE, VisitOutcome.WRONG_ADDRESS]]
    
    return {
        "account_id": account_id,
        "address": account.address,
        "normalized_address": account.normalized_address,
        "total_visits": len(visits),
        "successful_visits": len(successful),
        "failed_visits": len(failed),
        "visits": [
            {
                "visit_id": v.visit_id,
                "timestamp": v.timestamp,
                "latitude": v.latitude,
                "longitude": v.longitude,
                "outcome": v.outcome,
                "gps_accuracy": v.gps_accuracy,
                "dwell_time": v.dwell_time,
                "reliability_score": v.reliability_score,
                "integrity_score": v.integrity_score,
            }
            for v in visits
        ],
    }


@router.get("/accounts/{account_id}/history", response_model=List[Prediction])
async def get_prediction_history(
    account_id: str,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Get prediction history for an account."""
    prediction_repo = PredictionRepository(db)
    predictions = prediction_repo.get_history(account_id, limit)
    return [_deserialize_prediction(prediction) for prediction in predictions]


@router.get("/accounts/{account_id}/prediction", response_model=Prediction)
async def get_latest_prediction(
    account_id: str,
    db: Session = Depends(get_db),
):
    """Get latest prediction for an account."""
    prediction_repo = PredictionRepository(db)
    prediction = prediction_repo.get_latest_by_account(account_id)
    if not prediction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No prediction found for account {account_id}"
        )
    return _deserialize_prediction(prediction)


@router.get("/accounts", response_model=List[Account])
async def list_accounts(
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List accounts with optional search."""
    account_repo = AccountRepository(db)
    
    if search:
        accounts = account_repo.search(search, limit)
    else:
        accounts = account_repo.get_all(limit, offset)
    
    return accounts