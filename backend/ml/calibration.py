"""Confidence calibration for spatial predictions."""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple
from collections import defaultdict

import numpy as np
import joblib
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV

from config.settings import get_settings
from app.schemas import RecommendedAction


@dataclass
class CalibrationData:
    """Data for calibration."""
    predicted_confidences: List[float]
    actual_within_radius: List[bool]
    actual_distances: List[float]
    predicted_radii: List[float]


@dataclass
class CalibrationResult:
    """Result of calibration evaluation."""
    coverage: float
    mean_radius: float
    median_radius: float
    p90_radius: float
    calibration_error: float
    ece: float  # Expected Calibration Error
    reliability_diagram: List[Tuple[float, float, int]]  # (bin_center, accuracy, count)


class ConfidenceCalibrator:
    """Calibrates confidence scores to spatial coverage."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.settings = get_settings()
        self.method = self.config.get("method", self.settings.calibration_method)
        self.model_path = Path(self.config.get("model_path", self.settings.calibration_model_path))
        self.calibrator = None
        self._load_or_init()

    def _load_or_init(self):
        """Load or initialize calibrator."""
        if self.model_path.exists():
            try:
                self.calibrator = joblib.load(self.model_path)
            except Exception:
                self.calibrator = None
        else:
            self.calibrator = None

    def fit(self, predicted_confidences: List[float], 
            actual_distances: List[float],
            predicted_radii: List[float]) -> CalibrationResult:
        """Fit calibrator on validation data."""
        # Convert to binary: within predicted radius?
        actual_within = [
            1.0 if dist <= radius else 0.0
            for dist, radius in zip(actual_distances, predicted_radii)
        ]
        
        # Prepare data
        X = np.array(predicted_confidences).reshape(-1, 1)
        y = np.array(actual_within)
        
        # Fit calibrator based on method
        if self.method == "isotonic":
            self.calibrator = IsotonicRegression(out_of_bounds="clip", increasing=True)
            self.calibrator.fit(X.ravel(), y)
        elif self.method == "platt":
            lr = LogisticRegression(random_state=42)
            self.calibrator = CalibratedClassifierCV(lr, method="sigmoid", cv=3)
            self.calibrator.fit(X, y)
        else:
            # No calibration - identity
            self.calibrator = None
        
        # Save
        if self.calibrator:
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(self.calibrator, self.model_path)
        
        # Evaluate
        return self.evaluate(predicted_confidences, actual_distances, predicted_radii)

    def calibrate_confidence(self, confidence: float) -> float:
        """Calibrate a single confidence score."""
        if self.calibrator is None:
            return confidence
        
        if self.method == "isotonic":
            return float(self.calibrator.predict([confidence])[0])
        elif self.method == "platt":
            return float(self.calibrator.predict_proba([[confidence]])[0, 1])
        
        return confidence

    def calibrate_batch(self, confidences: List[float]) -> List[float]:
        """Calibrate multiple confidence scores."""
        if self.calibrator is None:
            return confidences
        
        X = np.array(confidences).reshape(-1, 1)
        
        if self.method == "isotonic":
            return self.calibrator.predict(X.ravel()).tolist()
        elif self.method == "platt":
            return self.calibrator.predict_proba(X)[:, 1].tolist()
        
        return confidences

    def predict_radius_from_confidence(self, confidence: float, 
                                        historical_errors: List[float] = None) -> float:
        """Predict confidence radius from calibrated confidence."""
        # Use empirical error distribution
        if historical_errors and len(historical_errors) > 10:
            # Radius = quantile of historical errors at confidence level
            calibrated_conf = self.calibrate_confidence(confidence)
            radius = np.percentile(historical_errors, calibrated_conf * 100)
            return float(max(10.0, radius))  # Minimum 10m
        
        # Fallback: heuristic based on confidence
        # Higher confidence -> smaller radius
        base_radius = 500.0  # meters at 0 confidence
        min_radius = 10.0
        radius = base_radius * (1.0 - confidence) + min_radius
        return radius

    def evaluate(self, predicted_confidences: List[float],
                 actual_distances: List[float],
                 predicted_radii: List[float]) -> CalibrationResult:
        """Evaluate calibration quality."""
        if not predicted_confidences:
            return CalibrationResult(0, 0, 0, 0, 0, 0, [])
        
        # Coverage: fraction within predicted radius
        within = [d <= r for d, r in zip(actual_distances, predicted_radii)]
        coverage = sum(within) / len(within)
        
        # Radius statistics
        mean_radius = np.mean(predicted_radii)
        median_radius = np.median(predicted_radii)
        p90_radius = np.percentile(predicted_radii, 90)
        
        # Calibration error: difference between predicted confidence and empirical coverage
        # Bin by confidence
        n_bins = 10
        bin_edges = np.linspace(0, 1, n_bins + 1)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        
        reliability = []
        total_ece = 0.0
        
        for i in range(n_bins):
            mask = (np.array(predicted_confidences) >= bin_edges[i]) & \
                   (np.array(predicted_confidences) < bin_edges[i+1])
            if i == n_bins - 1:
                mask = mask | (np.array(predicted_confidences) == 1.0)
            
            count = np.sum(mask)
            if count > 0:
                bin_confidence = np.mean(np.array(predicted_confidences)[mask])
                bin_accuracy = np.mean(np.array(within)[mask])
                reliability.append((bin_confidence, bin_accuracy, int(count)))
                total_ece += count / len(within) * abs(bin_confidence - bin_accuracy)
        
        # Overall calibration error (mean absolute difference)
        calibrated_confs = self.calibrate_batch(predicted_confidences) if self.calibrator else predicted_confidences
        calibration_error = np.mean(np.abs(np.array(calibrated_confs) - np.array(within)))
        
        return CalibrationResult(
            coverage=coverage,
            mean_radius=mean_radius,
            median_radius=median_radius,
            p90_radius=p90_radius,
            calibration_error=calibration_error,
            ece=total_ece,
            reliability_diagram=reliability,
        )


class SpatialUncertaintyEstimator:
    """Estimates spatial uncertainty (confidence radius) from multiple signals."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.settings = get_settings()
        self.min_radius = self.config.get("min_radius", 10.0)
        self.max_radius = self.config.get("max_radius", 5000.0)
        self.calibrator = ConfidenceCalibrator(config)
        
        # Historical error distribution (loaded from validation)
        self.historical_errors: List[float] = []

    def estimate(self, 
                 candidate: "CandidateLocation",
                 ranked_candidates: List["CandidateLocation"],
                 visit_reliabilities: List[float],
                 validation_errors: List[float] = None) -> Tuple[float, float]:
        """
        Estimate confidence and radius for best candidate.
        Returns: (confidence, radius_meters)
        """
        # 1. Base confidence from ranking probability
        base_confidence = candidate.probability or 0.5
        
        # 2. Evidence strength
        evidence_confidence = self._evidence_confidence(candidate, visit_reliabilities)
        
        # 3. Candidate agreement (entropy of top candidates)
        agreement_confidence = self._candidate_agreement(ranked_candidates)
        
        # 4. Combined confidence
        combined = (base_confidence * 0.5 + evidence_confidence * 0.3 + agreement_confidence * 0.2)
        combined = max(0.0, min(1.0, combined))
        
        # 5. Calibrate confidence
        calibrated = self.calibrator.calibrate_confidence(combined)
        
        # 6. Estimate radius
        if validation_errors:
            self.historical_errors = validation_errors
        
        radius = self.calibrator.predict_radius_from_confidence(calibrated, self.historical_errors)
        radius = max(self.min_radius, min(self.max_radius, radius))
        
        return calibrated, radius

    def _evidence_confidence(self, candidate: "CandidateLocation", 
                             visit_reliabilities: List[float]) -> float:
        """Confidence from evidence quality."""
        if not visit_reliabilities:
            return 0.3
        
        # Weighted average of visit reliabilities
        weights = []
        rels = []
        
        for v in visit_reliabilities:
            if v > 0:
                rels.append(v)
                weights.append(v)  # Self-weighting
        
        if not rels:
            return 0.2
        
        weighted_avg = sum(r * w for r, w in zip(rels, weights)) / sum(weights)
        
        # Boost by supporting visit count
        visit_boost = min(0.3, candidate.supporting_visit_count * 0.05)
        
        return min(1.0, weighted_avg + visit_boost)

    def _candidate_agreement(self, candidates: List["CandidateLocation"]) -> float:
        """Confidence from candidate agreement (low entropy = high confidence)."""
        if len(candidates) < 2:
            return 0.5
        
        probs = [c.probability or 0 for c in candidates[:5]]
        total = sum(probs)
        
        if total == 0:
            return 0.3
        
        # Normalize
        probs = [p / total for p in probs]
        
        # Entropy
        entropy = -sum(p * math.log(p + 1e-10) for p in probs if p > 0)
        max_entropy = math.log(len(probs))
        
        # Agreement = 1 - normalized entropy
        agreement = 1.0 - (entropy / max_entropy if max_entropy > 0 else 0)
        
        return max(0.0, min(1.0, agreement))

    def load_validation_errors(self, errors: List[float]):
        """Load historical validation errors for radius estimation."""
        self.historical_errors = errors
        self.calibrator.historical_errors = errors


def recommend_action(confidence: float, radius_m: float, 
                     config: dict = None) -> "RecommendedAction":
    """Determine recommended action based on confidence and radius."""
    settings = get_settings()
    
    direct_thresh = config.get("confidence_threshold_direct", settings.confidence_threshold_direct) if config else settings.confidence_threshold_direct
    verify_thresh = config.get("confidence_threshold_verify", settings.confidence_threshold_verify) if config else settings.confidence_threshold_verify
    direct_radius = config.get("direct_visit_radius_m", settings.direct_visit_radius_m) if config else settings.direct_visit_radius_m
    verify_radius = config.get("verification_radius_m", settings.verification_radius_m) if config else settings.verification_radius_m
    
    if confidence >= direct_thresh and radius_m <= direct_radius:
        return RecommendedAction.VISIT_DIRECTLY
    elif confidence >= verify_thresh and radius_m <= verify_radius:
        return RecommendedAction.VERIFY_FIRST
    else:
        return RecommendedAction.LOW_CONFIDENCE