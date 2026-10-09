"""Evaluation pipeline for geocoding model."""

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from collections import defaultdict

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from app.schemas import Prediction, Visit, VisitOutcome, CandidateLocation
from data.repositories import AccountRepository, VisitRepository, PredictionRepository
from data.database import db_session
from ml.address_normalizer import normalize_address
from ml.entity_extractor import extract_entities
from geospatial.candidate_generator import generate_candidates, CandidateGenerationContext
from geospatial.geocoder import geocode_address
from ml.ranker import rank_candidates, CandidateRanker
from ml.calibration import ConfidenceCalibrator, SpatialUncertaintyEstimator, recommend_action
from ml.visit_evidence import score_visit
from ml.visit_integrity import detect_integrity
from config.settings import get_settings


@dataclass
class EvaluationMetrics:
    """Evaluation metrics for geocoding."""
    median_error_m: float = 0.0
    mean_error_m: float = 0.0
    p75_error_m: float = 0.0
    p90_error_m: float = 0.0
    p95_error_m: float = 0.0
    within_50m: float = 0.0
    within_100m: float = 0.0
    within_250m: float = 0.0
    within_500m: float = 0.0
    confidence_coverage: float = 0.0
    calibration_error: float = 0.0
    mean_radius_m: float = 0.0
    median_radius_m: float = 0.0
    p90_radius_m: float = 0.0
    total_predictions: int = 0
    low_confidence_rate: float = 0.0


@dataclass
class BaselineResult:
    """Result from a baseline method."""
    name: str
    metrics: EvaluationMetrics
    predictions: list[dict] = field(default_factory=list)


class Evaluator:
    """Evaluates geocoding performance."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.settings = get_settings()

    def evaluate_predictions(self, 
                            predictions: list[Prediction],
                            ground_truth: dict[str, tuple[float, float]]) -> EvaluationMetrics:
        """Evaluate predictions against ground truth."""
        errors = []
        within_50 = 0
        within_100 = 0
        within_250 = 0
        within_500 = 0
        coverages = []
        radii = []
        low_conf_count = 0
        
        for pred in predictions:
            if pred.account_id not in ground_truth:
                continue
            
            true_lat, true_lon = ground_truth[pred.account_id]
            error = self._haversine(pred.latitude, pred.longitude, true_lat, true_lon)
            errors.append(error)
            
            if error <= 50:
                within_50 += 1
            if error <= 100:
                within_100 += 1
            if error <= 250:
                within_250 += 1
            if error <= 500:
                within_500 += 1
            
            # Coverage: is true location within predicted radius?
            covered = error <= pred.confidence_radius_m
            coverages.append(1.0 if covered else 0.0)
            radii.append(pred.confidence_radius_m)
            
            if pred.recommended_action.value == "LOW_CONFIDENCE":
                low_conf_count += 1
        
        if not errors:
            return EvaluationMetrics()
        
        errors = np.array(errors)
        radii = np.array(radii)
        
        return EvaluationMetrics(
            median_error_m=float(np.median(errors)),
            mean_error_m=float(np.mean(errors)),
            p75_error_m=float(np.percentile(errors, 75)),
            p90_error_m=float(np.percentile(errors, 90)),
            p95_error_m=float(np.percentile(errors, 95)),
            within_50m=within_50 / len(errors),
            within_100m=within_100 / len(errors),
            within_250m=within_250 / len(errors),
            within_500m=within_500 / len(errors),
            confidence_coverage=float(np.mean(coverages)),
            calibration_error=float(np.mean(np.abs(np.array(coverages) - np.array([p.confidence for p in predictions[:len(coverages)]])))),
            mean_radius_m=float(np.mean(radii)),
            median_radius_m=float(np.median(radii)),
            p90_radius_m=float(np.percentile(radii, 90)),
            total_predictions=len(errors),
            low_confidence_rate=low_conf_count / len(errors),
        )

    def evaluate_baseline_geocoder(self, 
                                    accounts: list,
                                    ground_truth: dict[str, tuple[float, float]]) -> BaselineResult:
        """Evaluate baseline: commercial geocoder only."""
        predictions = []
        
        for account in accounts:
            try:
                import asyncio
                results = asyncio.run(geocode_address(account.address, use_cache=True))
                if results:
                    pred = Prediction(
                        account_id=account.account_id,
                        latitude=results[0].latitude,
                        longitude=results[0].longitude,
                        confidence=0.5,
                        confidence_radius_m=500.0,
                        prediction_method="baseline_geocoder",
                        recommended_action="VERIFY_FIRST",
                        evidence={},
                        model_version="baseline",
                        feature_version="v1",
                    )
                    predictions.append(pred)
            except Exception:
                continue
        
        metrics = self.evaluate_predictions(predictions, ground_truth)
        return BaselineResult(
            name="Commercial Geocoder Only",
            metrics=metrics,
            predictions=[p.model_dump() for p in predictions],
        )

    def evaluate_baseline_nearest_visit(self,
                                         accounts: list,
                                         visits: list[Visit],
                                         ground_truth: dict[str, tuple[float, float]]) -> BaselineResult:
        """Evaluate baseline: nearest reliable historical visit."""
        predictions = []
        
        # Group visits by account
        visits_by_account = defaultdict(list)
        for visit in visits:
            visits_by_account[visit.account_id].append(visit)
        
        for account in accounts:
            account_visits = visits_by_account.get(account.account_id, [])
            successful = [v for v in account_visits if v.outcome in [VisitOutcome.SUCCESSFUL_CONTACT, VisitOutcome.PARTIAL_CONTACT]]
            
            if not successful:
                continue
            
            # Use most recent successful visit
            best_visit = max(successful, key=lambda v: v.timestamp)
            
            pred = Prediction(
                account_id=account.account_id,
                latitude=best_visit.latitude,
                longitude=best_visit.longitude,
                confidence=0.6,
                confidence_radius_m=200.0,
                prediction_method="baseline_nearest_visit",
                recommended_action="VERIFY_FIRST",
                evidence={},
                model_version="baseline",
                feature_version="v1",
            )
            predictions.append(pred)
        
        metrics = self.evaluate_predictions(predictions, ground_truth)
        return BaselineResult(
            name="Nearest Reliable Visit",
            metrics=metrics,
            predictions=[p.model_dump() for p in predictions],
        )

    def evaluate_baseline_weighted_centroid(self,
                                             accounts: list,
                                             visits: list[Visit],
                                             ground_truth: dict[str, tuple[float, float]]) -> BaselineResult:
        """Evaluate baseline: weighted historical visit centroid."""
        predictions = []
        
        visits_by_account = defaultdict(list)
        for visit in visits:
            visits_by_account[visit.account_id].append(visit)
        
        for account in accounts:
            account_visits = visits_by_account.get(account.account_id, [])
            successful = [v for v in account_visits if v.outcome in [VisitOutcome.SUCCESSFUL_CONTACT, VisitOutcome.PARTIAL_CONTACT]]
            
            if not successful:
                continue
            
            # Weighted centroid
            total_weight = 0
            weighted_lat = 0
            weighted_lon = 0
            
            for visit in successful:
                weight = 1.0
                if visit.gps_accuracy:
                    weight = 1.0 / max(1.0, visit.gps_accuracy)
                if visit.dwell_time:
                    weight *= min(2.0, visit.dwell_time / 300)
                
                weighted_lat += visit.latitude * weight
                weighted_lon += visit.longitude * weight
                total_weight += weight
            
            if total_weight > 0:
                pred = Prediction(
                    account_id=account.account_id,
                    latitude=weighted_lat / total_weight,
                    longitude=weighted_lon / total_weight,
                    confidence=0.6,
                    confidence_radius_m=250.0,
                    prediction_method="baseline_weighted_centroid",
                    recommended_action="VERIFY_FIRST",
                    evidence={},
                    model_version="baseline",
                    feature_version="v1",
                )
                predictions.append(pred)
        
        metrics = self.evaluate_predictions(predictions, ground_truth)
        return BaselineResult(
            name="Weighted Visit Centroid",
            metrics=metrics,
            predictions=[p.model_dump() for p in predictions],
        )

    def run_full_evaluation(self, 
                           accounts: list,
                           visits: list[Visit],
                           ground_truth: dict[str, tuple[float, float]]) -> dict:
        """Run full evaluation with all baselines and proposed model."""
        results = {}
        
        # Baselines
        results["baseline_geocoder"] = self.evaluate_baseline_geocoder(accounts, ground_truth)
        results["baseline_nearest_visit"] = self.evaluate_baseline_nearest_visit(accounts, visits, ground_truth)
        results["baseline_weighted_centroid"] = self.evaluate_baseline_weighted_centroid(accounts, visits, ground_truth)
        
        # Proposed model
        proposed_predictions = self._run_proposed_model(accounts, visits)
        proposed_metrics = self.evaluate_predictions(proposed_predictions, ground_truth)
        results["proposed"] = BaselineResult(
            name="Proposed (Candidate Ranking + Evidence Fusion)",
            metrics=proposed_metrics,
            predictions=[p.model_dump() for p in proposed_predictions],
        )
        
        return results

    def _run_proposed_model(self, accounts: list, visits: list[Visit]) -> list[Prediction]:
        """Run proposed model on accounts."""
        predictions = []
        ranker = CandidateRanker()
        uncertainty = SpatialUncertaintyEstimator()
        
        visits_by_account = defaultdict(list)
        for visit in visits:
            visits_by_account[visit.account_id].append(visit)
        
        for account in accounts:
            # Normalize
            normalized = extract_entities(account.address)
            
            # Get visits
            account_visits = visits_by_account.get(account.account_id, [])
            
            # Generate candidates
            context = CandidateGenerationContext(
                normalized_address=normalized,
                historical_visits=account_visits,
                nearby_accounts=[],
                place_clusters=[],
                geocoder_results=[],
            )
            candidates = generate_candidates(context)
            
            if not candidates:
                continue
            
            # Rank
            ranked = rank_candidates(candidates, normalized, account_visits, [], [], ranker)
            best = ranked[0]
            
            # Estimate confidence
            visit_reliabilities = []
            for visit in account_visits:
                if visit.outcome in [VisitOutcome.SUCCESSFUL_CONTACT, VisitOutcome.PARTIAL_CONTACT]:
                    reliability = score_visit(visit, account_visits)
                    visit_reliabilities.append(reliability.score)
            
            confidence, radius = uncertainty.estimate(best, ranked, visit_reliabilities)
            action = recommend_action(confidence, radius)
            
            pred = Prediction(
                account_id=account.account_id,
                latitude=best.latitude,
                longitude=best.longitude,
                confidence=confidence,
                confidence_radius_m=radius,
                prediction_method="candidate_ranking",
                recommended_action=action,
                evidence={},
                model_version=self.settings.model_version,
                feature_version=self.settings.feature_version,
            )
            predictions.append(pred)
        
        return predictions

    def _haversine(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Haversine distance in meters."""
        R = 6371000
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c


def run_evaluation():
    """Run evaluation and print results."""
    from data.database import db_session
    from data.repositories import AccountRepository, VisitRepository
    
    with db_session() as db:
        account_repo = AccountRepository(db)
        visit_repo = VisitRepository(db)
        
        accounts = account_repo.get_all(limit=100)
        visits = visit_repo.get_all_successful(limit=1000)
        
        # Build ground truth (in real scenario, this would be verified locations)
        # For demo, use account locations if available
        ground_truth = {}
        for account in accounts:
            if account.latitude and account.longitude:
                ground_truth[account.account_id] = (account.latitude, account.longitude)
        
        if not ground_truth:
            print("No ground truth available. Skipping evaluation.")
            return
        
        evaluator = Evaluator()
        results = evaluator.run_full_evaluation(accounts, visits, ground_truth)
        
        print("\n" + "="*80)
        print("EVALUATION RESULTS")
        print("="*80)
        
        for name, result in results.items():
            m = result.metrics
            print(f"\n{name}:")
            print(f"  Median Error: {m.median_error_m:.1f}m")
            print(f"  P90 Error: {m.p90_error_m:.1f}m")
            print(f"  Within 100m: {m.within_100m*100:.1f}%")
            print(f"  Within 500m: {m.within_500m*100:.1f}%")
            print(f"  Confidence Coverage: {m.confidence_coverage*100:.1f}%")
            print(f"  Calibration Error: {m.calibration_error:.3f}")
            print(f"  Total Predictions: {m.total_predictions}")


if __name__ == "__main__":
    run_evaluation()