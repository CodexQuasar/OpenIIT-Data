"""API routes for real dataset."""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from pathlib import Path

from data.real_data import RealDatasetLoader, load_dataset, get_dataset_loader
from geospatial.real_geocoder import RealDataGeocoder, GeocodingResult
from ml.address_normalizer import normalize_address
from ml.entity_extractor import extract_entities
from evaluation.ps3_experiments import run_ps3_experiments


router = APIRouter()


def get_geocoder() -> RealDataGeocoder:
    """Get geocoder with loaded dataset."""
    loader = get_dataset_loader()
    if not loader.accounts:
        loader.load_all("train")
    return RealDataGeocoder(loader)


@router.get("/real/accounts")
async def list_real_accounts(
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=128),
):
    """List real accounts."""
    loader = get_dataset_loader()
    if not loader.accounts:
        loader.load_all("train")

    accounts = list(loader.accounts.values())
    if search and search.strip():
        needle = search.strip().casefold()
        matching_ids = {
            account_id for account_id, account in loader.accounts.items()
            if needle in account_id.casefold()
            or needle in account.town_id.casefold()
            or needle in account.preferred_language.casefold()
            or any(
                needle in address.address_text.casefold()
                for address in loader.get_addresses_for_account(account_id)
            )
        }
        accounts = [account for account in accounts if account.account_id in matching_ids]
    accounts = accounts[offset:offset + limit]
    return [
        {
            "account_id": a.account_id,
            "town_id": a.town_id,
            "preferred_language": a.preferred_language,
            "portfolio": a.portfolio,
            "income_type": a.income_type,
        }
        for a in accounts
    ]


@router.get("/real/accounts/{account_id}")
async def get_real_account(account_id: str):
    """Get real account details."""
    loader = get_dataset_loader()
    if not loader.accounts:
        loader.load_all("train")

    account = loader.accounts.get(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    addresses = loader.get_addresses_for_account(account_id)
    visits = loader.get_visits_for_account(account_id)

    return {
        "account_id": account.account_id,
        "town_id": account.town_id,
        "preferred_language": account.preferred_language,
        "addresses": [
            {
                "address_id": a.address_id,
                "address_type": a.address_type,
                "address_text": a.address_text,
                "town_id": a.town_id,
            }
            for a in addresses
        ],
        "visits": [
            {
                "visit_id": v.visit_id,
                "visit_date": v.visit_date,
                "outcome": v.outcome,
                "dwell_s": v.dwell_s,
                "gps_accuracy_m": v.gps_accuracy_m,
            }
            for v in visits
        ],
    }


@router.get("/real/addresses/{address_id}/geocode")
async def geocode_real_address(address_id: str):
    """Geocode a real address."""
    geocoder = get_geocoder()
    result = geocoder.geocode_address(address_id)

    if not result:
        raise HTTPException(status_code=404, detail="Address not found")

    return {
        "address_id": result.address_id,
        "account_id": result.account_id,
        "predicted_x": result.predicted_x,
        "predicted_y": result.predicted_y,
        "confidence": result.confidence,
        "confidence_radius_m": result.confidence_radius_m,
        "recommended_action": result.recommended_action,
        "prediction_method": result.prediction_method,
        "evidence": result.evidence,
        "ground_truth_x": result.ground_truth_x,
        "ground_truth_y": result.ground_truth_y,
        "error_m": result.error_m,
    }


@router.get("/real/evaluate")
async def evaluate_real_data():
    """Evaluate geocoder on surveyed addresses."""
    geocoder = get_geocoder()
    results = geocoder.evaluate_on_surveyed()
    return results


@router.get("/real/evaluation/ps3")
async def evaluate_ps3_experiments(
    split: str = Query("train", pattern="^(train|val|test)$"),
):
    """Run and persist the versioned PS3 evaluation artifact."""
    loader = get_dataset_loader()
    output_dir = Path(__file__).resolve().parents[3] / "evaluation_artifacts"
    return run_ps3_experiments(loader.dataset_path, split=split, output_dir=output_dir)


@router.get("/real/addresses/{address_id}")
async def get_real_address(address_id: str):
    """Get real address details."""
    loader = get_dataset_loader()
    if not loader.addresses:
        loader.load_all("train")

    address = loader.addresses.get(address_id)
    if not address:
        raise HTTPException(status_code=404, detail="Address not found")

    visits = loader.get_visits_for_address(address_id)
    baseline = loader.baseline_geocodes.get(address_id)
    surveyed = loader.surveyed_addresses.get(address_id)

    return {
        "address_id": address.address_id,
        "account_id": address.account_id,
        "address_type": address.address_type,
        "address_text": address.address_text,
        "town_id": address.town_id,
        "baseline_geocode": {
            "x": baseline.geocoder_x,
            "y": baseline.geocoder_y,
            "precision": baseline.precision,
        } if baseline else None,
        "surveyed": {
            "x": surveyed.surveyed_x,
            "y": surveyed.surveyed_y,
        } if surveyed else None,
        "visits": [
            {
                "visit_id": v.visit_id,
                "visit_date": v.visit_date,
                "outcome": v.outcome,
                "checkin_x": v.checkin_x,
                "checkin_y": v.checkin_y,
                "gps_accuracy_m": v.gps_accuracy_m,
                "dwell_s": v.dwell_s,
                "remark": v.remark,
            }
            for v in visits
        ],
    }


@router.get("/real/towns")
async def list_towns():
    """List all towns."""
    loader = get_dataset_loader()
    if not loader.towns:
        loader.load_all("train")

    return [
        {
            "town_id": t.town_id,
            "town_name": t.town_name,
            "address_style": t.address_style,
            "approx_radius_m": t.approx_radius_m,
        }
        for t in loader.towns.values()
    ]


@router.get("/real/landmarks")
async def list_landmarks(town_id: Optional[str] = None):
    """List landmarks, optionally filtered by town."""
    loader = get_dataset_loader()
    if not loader.landmarks:
        loader.load_all("train")

    landmarks = loader.landmarks.values()
    if town_id:
        landmarks = [l for l in landmarks if l.town_id == town_id]

    return [
        {
            "poi_id": l.poi_id,
            "town_id": l.town_id,
            "landmark_type": l.landmark_type,
            "name": l.name,
            "x": l.x,
            "y": l.y,
        }
        for l in landmarks
    ]