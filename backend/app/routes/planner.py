"""Visit-planner and right-party-contact integration surfaces."""
from fastapi import APIRouter, Depends, Query
from math import cos, radians, sqrt
from sqlalchemy.orm import Session
from data.database import get_db
from data.models import AccountModel, VisitModel
from app.auth.dependencies import require_visit_read

router = APIRouter()


@router.get("/planner/visits")
async def plan_visits(
    limit: int = Query(100, ge=1, le=1000),
    origin_latitude: float | None = Query(None, ge=-90, le=90),
    origin_longitude: float | None = Query(None, ge=-180, le=180),
    max_distance_km: float | None = Query(None, gt=0, le=500),
    db: Session = Depends(get_db),
    _user=Depends(require_visit_read),
):
    """Return explainable visit priorities based on confidence and age."""
    accounts = db.query(AccountModel).filter(
        AccountModel.latitude.isnot(None),
        AccountModel.longitude.isnot(None),
    ).all()
    result = []
    for account in accounts:
        distance_km = None
        if origin_latitude is not None and origin_longitude is not None:
            lat_delta = (account.latitude - origin_latitude) * 111.32
            lon_delta = (account.longitude - origin_longitude) * 111.32 * cos(radians(origin_latitude))
            distance_km = sqrt(lat_delta * lat_delta + lon_delta * lon_delta)
            if max_distance_km is not None and distance_km > max_distance_km:
                continue
        action = "verify_first" if (account.confidence or 0) < 0.5 else "visit_directly"
        result.append({
            "account_id": account.account_id,
            "latitude": account.latitude,
            "longitude": account.longitude,
            "confidence": account.confidence,
            "confidence_radius_m": account.confidence_radius_m,
            "location_source": account.location_source,
            "recommended_action": action,
            "reason": "low_location_confidence" if action == "verify_first" else "confirmed_or_high_confidence",
            "distance_km": distance_km,
        })
    return sorted(
        result,
        key=lambda item: (
            item["recommended_action"] != "verify_first",
            item["distance_km"] is None,
            item["distance_km"] if item["distance_km"] is not None else 0,
            -(item["confidence"] or 0),
        ),
    )[:limit]


@router.get("/rpc/location-features/{account_id}")
async def rpc_location_features(
    account_id: str,
    db: Session = Depends(get_db),
    _user=Depends(require_visit_read),
):
    """Stable PS2 feature contract for the address-health model."""
    account = db.query(AccountModel).filter(AccountModel.account_id == account_id).first()
    if not account:
        return {"account_id": account_id, "location_confidence": None, "address_health_features": {}}
    visits = db.query(VisitModel).filter(VisitModel.account_id == account_id).all()
    return {
        "account_id": account_id,
        "location_confidence": account.confidence,
        "confidence_radius_m": account.confidence_radius_m,
        "location_source": account.location_source,
        "address_health_features": {
            "successful_visits": sum(v.outcome.value in ("SUCCESSFUL_CONTACT", "PARTIAL_CONTACT") for v in visits),
            "failed_searches": sum(v.outcome.value in ("FAILED_SEARCH", "ADDRESS_NOT_TRACEABLE") for v in visits),
            "confirmed_location": account.confirmed_latitude is not None,
        },
    }
