"""Metrics routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
import math

from data.database import get_db
from data.repositories import AccountRepository, VisitRepository, PredictionRepository
from data.models import AccountModel, VisitModel, PredictionModel
from app.schemas import MetricsResponse, VisitOutcome, RecommendedAction
from geospatial.real_geocoder import RealDataGeocoder
from data.real_data import get_dataset_loader

router = APIRouter()

# Cache for evaluation results
_evaluation_cache = None


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance between two WGS84 coordinates."""
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _database_calibration(db: Session) -> dict:
    """Calibrate predictions against the first reliable visit after prediction."""
    rows = []
    for prediction in db.query(PredictionModel).all():
        visit = db.query(VisitModel).filter(
            VisitModel.account_id == prediction.account_id,
            VisitModel.timestamp >= prediction.timestamp,
            VisitModel.outcome.in_([VisitOutcome.SUCCESSFUL_CONTACT, VisitOutcome.PARTIAL_CONTACT]),
        ).order_by(VisitModel.timestamp.asc()).first()
        if visit is None:
            continue
        distance = _distance_m(prediction.latitude, prediction.longitude, visit.latitude, visit.longitude)
        rows.append((prediction.confidence, distance <= prediction.confidence_radius_m, distance))

    if not rows:
        return {"bins": [], "overall_ece": None, "sample_count": 0}

    bins = []
    ece = 0.0
    for index in range(10):
        low, high = index / 10, (index + 1) / 10
        selected = [row for row in rows if low <= row[0] < high or (index == 9 and row[0] == 1.0)]
        if not selected:
            continue
        predicted = sum(row[0] for row in selected) / len(selected)
        actual = sum(1 for row in selected if row[1]) / len(selected)
        ece += len(selected) / len(rows) * abs(predicted - actual)
        bins.append({
            "bin": f"{low:.1f}-{high:.1f}",
            "predicted": predicted,
            "actual": actual,
            "count": len(selected),
        })
    return {"bins": bins, "overall_ece": ece, "sample_count": len(rows)}


def _get_evaluation_results() -> dict:
    """Get or compute evaluation results on real dataset."""
    global _evaluation_cache
    if _evaluation_cache is None:
        try:
            loader = get_dataset_loader()
            if not loader.accounts:
                loader.load_all("train")
            geocoder = RealDataGeocoder(loader)
            _evaluation_cache = geocoder.evaluate_on_surveyed()
        except Exception:
            _evaluation_cache = {}
    return _evaluation_cache


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(db: Session = Depends(get_db)):
    """Get system-wide metrics."""
    account_repo = AccountRepository(db)
    visit_repo = VisitRepository(db)
    prediction_repo = PredictionRepository(db)
    
    # Total counts
    total_accounts = account_repo.count()
    total_visits = db.query(VisitModel).count()
    
    # Predictions made
    predictions_made = db.query(PredictionModel).count()
    
    # High confidence rate
    high_conf_predictions = db.query(PredictionModel).filter(
        PredictionModel.confidence >= 0.85
    ).count()
    high_confidence_rate = high_conf_predictions / predictions_made if predictions_made > 0 else 0
    
    # Address not traceable rate
    not_traceable = db.query(VisitModel).filter(
        VisitModel.outcome == VisitOutcome.ADDRESS_NOT_TRACEABLE
    ).count()
    address_not_traceable_rate = not_traceable / total_visits if total_visits > 0 else 0
    
    # Productive visits
    productive_visits = db.query(VisitModel).filter(
        VisitModel.outcome.in_([VisitOutcome.SUCCESSFUL_CONTACT, VisitOutcome.PARTIAL_CONTACT])
    ).count()
    
    # Error metrics from real dataset evaluation
    eval_results = _get_evaluation_results()
    median_error_m = eval_results.get("median_error_m")
    p90_error_m = eval_results.get("p90_error_m")
    confidence_coverage = eval_results.get("within_500m")  # Coverage within 500m
    calibration = _database_calibration(db)
    calibration_error = calibration["overall_ece"]
    
    return MetricsResponse(
        total_accounts=total_accounts,
        total_visits=total_visits,
        predictions_made=predictions_made,
        high_confidence_rate=high_confidence_rate,
        median_error_m=median_error_m,
        p90_error_m=p90_error_m,
        confidence_coverage=confidence_coverage,
        calibration_error=calibration_error,
        address_not_traceable_rate=address_not_traceable_rate,
        productive_visits=productive_visits,
        within_50m=eval_results.get("within_50m"),
        within_100m=eval_results.get("within_100m"),
        within_250m=eval_results.get("within_250m"),
        within_500m=eval_results.get("within_500m"),
    )


@router.get("/metrics/by-territory")
async def get_territory_metrics(
    territory_type: str = "city",  # city, district, pincode, locality
    db: Session = Depends(get_db),
):
    """Get metrics broken down by territory."""
    try:
        # Prefer persisted production evidence when available.
        grouped = {}
        predictions = db.query(PredictionModel).all()
        for prediction in predictions:
            account = db.query(AccountModel).filter(
                AccountModel.account_id == prediction.account_id
            ).first()
            if not account:
                continue
            territory = getattr(account, territory_type, None) or account.city or "unknown"
            visit = db.query(VisitModel).filter(
                VisitModel.account_id == prediction.account_id,
                VisitModel.timestamp >= prediction.timestamp,
                VisitModel.outcome.in_([VisitOutcome.SUCCESSFUL_CONTACT, VisitOutcome.PARTIAL_CONTACT]),
            ).order_by(VisitModel.timestamp.asc()).first()
            if visit is None:
                continue
            entry = grouped.setdefault(territory, {"errors": [], "covered": 0, "total": 0, "account_ids": set()})
            error = _distance_m(prediction.latitude, prediction.longitude, visit.latitude, visit.longitude)
            entry["errors"].append(error)
            entry["total"] += 1
            entry["covered"] += int(error <= prediction.confidence_radius_m)
            entry["account_ids"].add(account.account_id)

        if grouped:
            metrics = []
            for territory, entry in grouped.items():
                errors = sorted(entry["errors"])
                n = len(errors)
                metrics.append({
                    "territory": territory,
                    "accounts": len(entry["account_ids"]),
                    "evaluated_predictions": n,
                    "accuracy": entry["covered"] / n,
                    "median_error_m": errors[n // 2],
                    "p90_error_m": errors[min(n - 1, int(n * 0.9))],
                    "confidence_coverage": entry["covered"] / n,
                    "not_traceable_rate": db.query(VisitModel).filter(
                        VisitModel.outcome == VisitOutcome.ADDRESS_NOT_TRACEABLE
                    ).count() / max(1, db.query(VisitModel).count()),
                })
            return {"territory_type": territory_type, "metrics": metrics, "source": "operational_database"}

        loader = get_dataset_loader()
        if not loader.towns:
            loader.load_all("train")
        
        # Run evaluation per town to get territory-level accuracy
        geocoder = RealDataGeocoder(loader)
        eval_results = geocoder.evaluate_on_surveyed()
        
        # Get per-town breakdown by evaluating each town separately
        town_metrics = []
        for town in loader.towns.values():
            # Get surveyed addresses in this town
            town_addresses = [a for a in loader.addresses.values() if a.town_id == town.town_id]
            town_surveyed = [addr_id for addr_id in loader.surveyed_addresses if addr_id in [a.address_id for a in town_addresses]]
            
            if town_surveyed:
                town_errors = []
                for addr_id in town_surveyed:
                    result = geocoder.geocode_address(addr_id)
                    if result and result.error_m is not None:
                        town_errors.append(result.error_m)
                
                if town_errors:
                    town_errors.sort()
                    n = len(town_errors)
                    town_metrics.append({
                        "territory": town.town_name,
                        "town_id": town.town_id,
                        "accounts": len([a for a in loader.accounts.values() if a.town_id == town.town_id]),
                        "surveyed_addresses": n,
                        "accuracy": sum(1 for e in town_errors if e <= 250) / n,
                        "median_error_m": town_errors[n // 2],
                        "mean_error_m": sum(town_errors) / n,
                        "p90_error_m": town_errors[int(n * 0.9)],
                        "within_50m": sum(1 for e in town_errors if e <= 50) / n,
                        "within_100m": sum(1 for e in town_errors if e <= 100) / n,
                        "within_250m": sum(1 for e in town_errors if e <= 250) / n,
                        "within_500m": sum(1 for e in town_errors if e <= 500) / n,
                    })
        
        return {
            "territory_type": "town",
            "metrics": town_metrics,
            "overall": eval_results,
        }
    except Exception as e:
        return {
            "territory_type": territory_type,
            "metrics": [],
            "error": str(e),
        }


@router.get("/metrics/productivity")
async def get_productivity_metrics(db: Session = Depends(get_db)):
    """Measure productive visits per agent-day from operational visit logs."""
    visits = db.query(VisitModel).all()
    by_agent_day = {}
    for visit in visits:
        key = (visit.agent_id, visit.timestamp.date().isoformat())
        entry = by_agent_day.setdefault(key, {"visits": 0, "productive": 0, "not_traceable": 0})
        entry["visits"] += 1
        entry["productive"] += int(visit.outcome in [VisitOutcome.SUCCESSFUL_CONTACT, VisitOutcome.PARTIAL_CONTACT])
        entry["not_traceable"] += int(visit.outcome == VisitOutcome.ADDRESS_NOT_TRACEABLE)
    days = len(by_agent_day)
    return {
        "agent_days": days,
        "productive_visits": sum(item["productive"] for item in by_agent_day.values()),
        "visits": sum(item["visits"] for item in by_agent_day.values()),
        "productive_visits_per_agent_day": (
            sum(item["productive"] for item in by_agent_day.values()) / days if days else 0
        ),
        "not_traceable_rate": (
            sum(item["not_traceable"] for item in by_agent_day.values()) /
            max(1, sum(item["visits"] for item in by_agent_day.values()))
        ),
        "source": "operational_database",
    }
@router.get("/metrics/confidence-calibration")
async def get_confidence_calibration(db: Session = Depends(get_db)):
    """Get confidence calibration data for reliability diagram."""
    try:
        database_results = _database_calibration(db)
        if database_results["sample_count"] > 0:
            return database_results
        loader = get_dataset_loader()
        if not loader.accounts:
            loader.load_all("train")
        geocoder = RealDataGeocoder(loader)
        calibration_results = geocoder.evaluate_calibration()
        return calibration_results
    except Exception as exc:
        return {"bins": [], "overall_ece": None, "sample_count": 0, "error": str(exc)}


@router.get("/metrics/error-distribution")
async def get_error_distribution(db: Session = Depends(get_db)):
    """Get error distribution for visualization."""
    eval_results = _get_evaluation_results()
    
    distribution = []
    if eval_results.get("total_evaluated", 0) > 0:
        distribution = [
            {"range": "0-50m", "count": int(eval_results.get("within_50m", 0) * eval_results.get("total_evaluated", 0))},
            {"range": "50-100m", "count": int((eval_results.get("within_100m", 0) - eval_results.get("within_50m", 0)) * eval_results.get("total_evaluated", 0))},
            {"range": "100-250m", "count": int((eval_results.get("within_250m", 0) - eval_results.get("within_100m", 0)) * eval_results.get("total_evaluated", 0))},
            {"range": "250-500m", "count": int((eval_results.get("within_500m", 0) - eval_results.get("within_250m", 0)) * eval_results.get("total_evaluated", 0))},
            {"range": "500-1000m", "count": int((eval_results.get("within_1000m", 0) - eval_results.get("within_500m", 0)) * eval_results.get("total_evaluated", 0))},
            {"range": ">1000m", "count": int((1 - eval_results.get("within_1000m", 0)) * eval_results.get("total_evaluated", 0))},
        ]
    
    percentiles = {
        "p50": eval_results.get("median_error_m", 0),
        "p90": eval_results.get("p90_error_m", 0),
        "p95": eval_results.get("p90_error_m", 0) * 1.2 if eval_results.get("p90_error_m") else 0,
        "max": eval_results.get("max_error_m", 0),
    }
    
    return {
        "distribution": distribution,
        "percentiles": percentiles,
    }