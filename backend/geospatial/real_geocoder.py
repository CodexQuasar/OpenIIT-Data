"""Real dataset geocoder bridge - connects production geocoder with evaluation dataset."""

from dataclasses import dataclass
from typing import Optional, List
from pathlib import Path

from data.real_data import RealDatasetLoader, RealSurveyedAddress, get_dataset_loader
from geospatial.candidate_generator import generate_candidates, CandidateGenerationContext
from geospatial.geocoder import geocode_address
from ml.ranker import rank_candidates, CandidateRanker
from ml.calibration import ConfidenceCalibrator, recommend_action, SpatialUncertaintyEstimator
from ml.visit_evidence import score_visit
from ml.address_normalizer import normalize_address
from ml.entity_extractor import extract_entities
from geospatial.directions import generate_directions
from app.schemas import (
    CandidateLocation, CandidateSource, NormalizedAddress, 
    Account, Visit, PlaceCluster, VisitOutcome, RecommendedAction,
    PredictionEvidence, Prediction
)
from config.settings import get_settings


@dataclass
class GeocodingResult:
    """Result of geocoding a real dataset address."""
    address_id: str
    account_id: str
    predicted_x: Optional[float]
    predicted_y: Optional[float]
    confidence: float
    confidence_radius_m: Optional[float]
    recommended_action: RecommendedAction
    prediction_method: str
    evidence: dict
    ground_truth_x: Optional[float]
    ground_truth_y: Optional[float]
    error_m: Optional[float]


class RealDataGeocoder:
    """Geocoder for real dataset evaluation using production pipeline."""
    
    def __init__(self, loader: RealDatasetLoader):
        self.loader = loader
        self.settings = get_settings()
        self.ranker = CandidateRanker()
        self.calibrator = ConfidenceCalibrator()
        self.uncertainty = SpatialUncertaintyEstimator()
    
    def geocode_address(self, address_id: str) -> Optional[GeocodingResult]:
        """Geocode a single address from the real dataset."""
        # Get address from dataset
        address = self.loader.addresses.get(address_id)
        if not address:
            return None
        
        surveyed = self.loader.surveyed_addresses.get(address_id)
        ground_truth_x = surveyed.surveyed_x if surveyed else None
        ground_truth_y = surveyed.surveyed_y if surveyed else None
        
        # Get historical visits for this address
        visits = self.loader.get_visits_for_address(address_id)
        
        # Convert to schema objects
        historical_visits = self._convert_visits(visits)
        
        # Normalize address
        normalized = extract_entities(address.address_text)
        
        # Get baseline geocode
        baseline = self.loader.baseline_geocodes.get(address_id)
        geocoder_results = []
        if baseline:
            geocoder_results = [CandidateLocation(
                candidate_id="baseline",
                latitude=baseline.geocoder_x,
                longitude=baseline.geocoder_y,
                source=CandidateSource.GEOCODER,
                commercial_geocoder_distance=0.0,
                gps_accuracy=100.0,
            )]
        
        # The PS3 coordinates are projected local x/y meters. Do not fabricate
        # WGS84 account coordinates from a town radius.
        nearby_accounts = []
        account = self.loader.accounts.get(address.account_id)
        
        # Get place clusters - use locality centroids as place clusters
        place_clusters = []
        if account and account.town_id:
            for locality in self.loader.get_localities_for_town(account.town_id):
                place_clusters.append(PlaceCluster(
                    cluster_id=locality.locality_id,
                    latitude=locality.centroid_x,
                    longitude=locality.centroid_y,
                    account_ids=[a.account_id for a in self.loader.accounts.values() if a.town_id == account.town_id],
                    landmarks=[],
                    address_variants=[],
                    visit_count=len([
                        v for v in self.loader.field_visits.values()
                        if self.loader.accounts.get(v.account_id)
                        and self.loader.accounts[v.account_id].town_id == account.town_id
                    ]),
                    confidence=0.5,
                ))
        
        # Generate candidates
        candidates = generate_candidates(
            normalized,
            historical_visits,
            nearby_accounts,
            place_clusters,
            geocoder_results,
            {"coordinate_system": "projected_xy"},
        )
        
        if not candidates:
            return GeocodingResult(
                address_id=address_id,
                account_id=address.account_id,
                predicted_x=None,
                predicted_y=None,
                confidence=0.0,
                confidence_radius_m=None,
                recommended_action=RecommendedAction.LOW_CONFIDENCE,
                prediction_method="no_candidates",
                evidence={"strongest_evidence": ["No candidates generated"]},
                ground_truth_x=ground_truth_x,
                ground_truth_y=ground_truth_y,
                error_m=None,
            )
        
        # Rank candidates
        ranked = rank_candidates(candidates, normalized, historical_visits, nearby_accounts, place_clusters, self.ranker)
        best = ranked[0]
        
        # Score visit reliabilities
        visit_reliabilities = []
        for visit in historical_visits:
            if visit.outcome in [VisitOutcome.SUCCESSFUL_CONTACT, VisitOutcome.PARTIAL_CONTACT]:
                reliability = score_visit(visit, historical_visits)
                visit_reliabilities.append(reliability.score)
        
        # Estimate confidence and radius
        confidence, radius = self.uncertainty.estimate(best, ranked, visit_reliabilities)
        
        # Calibrate confidence
        calibrated_confidence = self.calibrator.calibrate_confidence(confidence)
        
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
            strongest_evidence=self._build_evidence_strings(best, historical_visits, nearby_accounts),
        )
        
        # Calculate error if ground truth available
        error_m = None
        if ground_truth_x is not None and ground_truth_y is not None:
            import math
            error_m = math.sqrt((best.latitude - ground_truth_x)**2 + (best.longitude - ground_truth_y)**2)
        
        return GeocodingResult(
            address_id=address_id,
            account_id=address.account_id,
            predicted_x=best.latitude,
            predicted_y=best.longitude,
            confidence=calibrated_confidence,
            confidence_radius_m=radius,
            recommended_action=action,
            prediction_method="candidate_ranking",
            evidence=evidence.model_dump(),
            ground_truth_x=ground_truth_x,
            ground_truth_y=ground_truth_y,
            error_m=error_m,
        )
    
    def evaluate_on_surveyed(self) -> dict:
        """Evaluate geocoder on all surveyed addresses."""
        results = []
        errors = []
        
        for address_id in self.loader.surveyed_addresses:
            result = self.geocode_address(address_id)
            if result and result.error_m is not None:
                results.append(result)
                errors.append(result.error_m)
        
        if not errors:
            return {"total_evaluated": 0, "error": "No surveyed addresses with ground truth"}
        
        errors.sort()
        n = len(errors)
        
        # Collect confidence vs accuracy data for calibration
        confidences = [r.confidence for r in results]
        accuracies = [1 if r.error_m and r.error_m <= 250 else 0 for r in results]
        
        baseline_errors = []
        for address_id, surveyed in self.loader.surveyed_addresses.items():
            baseline = self.loader.baseline_geocodes.get(address_id)
            if baseline:
                baseline_errors.append(((baseline.geocoder_x - surveyed.surveyed_x) ** 2 +
                                        (baseline.geocoder_y - surveyed.surveyed_y) ** 2) ** 0.5)

        def summarize(values: list[float]) -> dict:
            if not values:
                return {"total_evaluated": 0}
            values = sorted(values)
            count = len(values)
            return {
                "total_evaluated": count,
                "median_error_m": values[count // 2],
                "p90_error_m": values[min(count - 1, int(count * 0.9))],
                "within_250m": sum(value <= 250 for value in values) / count,
                "within_500m": sum(value <= 500 for value in values) / count,
            }

        return {
            "total_evaluated": n,
            "median_error_m": errors[n // 2],
            "mean_error_m": sum(errors) / n,
            "p75_error_m": errors[min(n - 1, int(n * 0.75))],
            "p90_error_m": errors[int(n * 0.9)],
            "p95_error_m": errors[min(n - 1, int(n * 0.95))],
            "max_error_m": max(errors),
            "min_error_m": min(errors),
            "within_50m": sum(1 for e in errors if e <= 50) / n,
            "within_100m": sum(1 for e in errors if e <= 100) / n,
            "within_250m": sum(1 for e in errors if e <= 250) / n,
            "within_500m": sum(1 for e in errors if e <= 500) / n,
            "within_1000m": sum(1 for e in errors if e <= 1000) / n,
            "calibration_data": {
                "confidences": confidences,
                "accuracies": accuracies,
            },
            "baselines": {
                "commercial_geocoder": summarize(baseline_errors),
            },
        }
    
    def evaluate_calibration(self) -> dict:
        """Evaluate confidence calibration on surveyed addresses."""
        eval_results = self.evaluate_on_surveyed()
        
        if eval_results.get("total_evaluated", 0) == 0:
            return {"bins": [], "overall_ece": 0.0}
        
        calibration_data = eval_results.get("calibration_data", {})
        confidences = calibration_data.get("confidences", [])
        accuracies = calibration_data.get("accuracies", [])
        
        if not confidences or not accuracies:
            return {"bins": [], "overall_ece": 0.0}
        
        # Bin confidences into 10 bins (0.0-0.1, 0.1-0.2, ..., 0.9-1.0)
        bins = []
        ece = 0.0
        total_samples = len(confidences)
        
        for i in range(10):
            bin_low = i * 0.1
            bin_high = (i + 1) * 0.1
            bin_center = (bin_low + bin_high) / 2
            
            # Find samples in this bin
            bin_indices = [j for j, c in enumerate(confidences) if bin_low <= c < bin_high]
            
            if bin_indices:
                bin_confidences = [confidences[j] for j in bin_indices]
                bin_accuracies = [accuracies[j] for j in bin_indices]
                
                avg_confidence = sum(bin_confidences) / len(bin_confidences)
                accuracy = sum(bin_accuracies) / len(bin_accuracies)
                count = len(bin_indices)
            else:
                avg_confidence = bin_center
                accuracy = 0.0
                count = 0
            
            bins.append({
                "bin": f"{bin_low:.1f}-{bin_high:.1f}",
                "predicted": avg_confidence,
                "actual": accuracy,
                "count": count,
            })
            
            # Expected Calibration Error
            if count > 0:
                ece += (count / total_samples) * abs(avg_confidence - accuracy)
        
        return {
            "bins": bins,
            "overall_ece": ece,
        }
    
    def _convert_visits(self, visits: List) -> List[Visit]:
        """Convert dataset visits to schema objects."""
        schema_visits = []
        for v in visits:
            # Map dataset outcome to schema outcome
            outcome_map = {
                'met_borrower': VisitOutcome.SUCCESSFUL_CONTACT,
                'met_family': VisitOutcome.PARTIAL_CONTACT,
                'locked_premises': VisitOutcome.FAILED_SEARCH,
                'address_not_traceable': VisitOutcome.ADDRESS_NOT_TRACEABLE,
                'no_such_person': VisitOutcome.ADDRESS_NOT_TRACEABLE,
                'cash_collected': VisitOutcome.SUCCESSFUL_CONTACT,
                'neighbour_says_shifted': VisitOutcome.FAILED_SEARCH,
            }
            
            # PS_3 stores local projected x/y coordinates, not WGS84
            # latitude/longitude. Use a validated Visit for normal GPS data,
            # but preserve the dataset coordinates for evaluation.
            schema_visits.append(Visit.model_construct(
                visit_id=v.visit_id,
                account_id=v.account_id,
                agent_id=v.agent_id,
                timestamp=v.checkin_ts,
                latitude=v.checkin_x,
                longitude=v.checkin_y,
                gps_accuracy=v.gps_accuracy_m,
                outcome=outcome_map.get(v.outcome, VisitOutcome.OTHER),
                dwell_time=v.dwell_s,
                remarks=v.remark,
                trajectory=[],
                integrity_score=None,
                reliability_score=None,
                created_at=v.checkin_ts,
            ))
        return schema_visits
    
    def _build_evidence_strings(
        self,
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