"""Tests for confidence calibration."""

import pytest
import numpy as np
from ml.calibration import ConfidenceCalibrator, SpatialUncertaintyEstimator, recommend_action
from app.schemas import CandidateLocation, RecommendedAction


class TestConfidenceCalibrator:
    """Test confidence calibration."""

    def setup_method(self):
        self.calibrator = ConfidenceCalibrator()

    def test_calibrate_confidence_range(self):
        """Test calibrated confidence is in valid range."""
        conf = self.calibrator.calibrate_confidence(0.5)
        assert 0.0 <= conf <= 1.0

    def test_predict_radius_positive(self):
        """Test predicted radius is positive."""
        radius = self.calibrator.predict_radius_from_confidence(0.8)
        assert radius > 0

    def test_higher_confidence_smaller_radius(self):
        """Test higher confidence gives smaller radius."""
        r1 = self.calibrator.predict_radius_from_confidence(0.9)
        r2 = self.calibrator.predict_radius_from_confidence(0.5)
        assert r1 < r2

    def test_evaluate_empty(self):
        """Test evaluation with empty data."""
        result = self.calibrator.evaluate([], [], [])
        assert result.coverage == 0

    def test_evaluate_perfect_calibration(self):
        """Test evaluation with perfect calibration."""
        confidences = [0.5, 0.6, 0.7, 0.8, 0.9]
        distances = [50, 60, 70, 80, 90]
        radii = [100, 100, 100, 100, 100]
        result = self.calibrator.evaluate(confidences, distances, radii)
        assert result.coverage == 1.0


class TestSpatialUncertaintyEstimator:
    """Test spatial uncertainty estimation."""

    def setup_method(self):
        self.estimator = SpatialUncertaintyEstimator()

    def test_estimate_returns_valid_values(self):
        """Test estimation returns valid confidence and radius."""
        candidate = CandidateLocation(
            candidate_id="c1",
            latitude=12.9716,
            longitude=77.5946,
            source="HISTORICAL_VISIT",
            probability=0.8,
            supporting_visit_count=3,
            visit_integrity=0.9,
        )
        candidates = [candidate]
        reliabilities = [0.8, 0.9, 0.7]
        
        confidence, radius = self.estimator.estimate(candidate, candidates, reliabilities)
        assert 0.0 <= confidence <= 1.0
        assert radius > 0

    def test_evidence_confidence(self):
        """Test evidence confidence calculation."""
        candidate = CandidateLocation(
            candidate_id="c1",
            latitude=12.9716,
            longitude=77.5946,
            source="HISTORICAL_VISIT",
            supporting_visit_count=5,
        )
        reliabilities = [0.9, 0.8, 0.9, 0.7, 0.8]
        conf = self.estimator._evidence_confidence(candidate, reliabilities)
        assert conf > 0.7

    def test_candidate_agreement(self):
        """Test candidate agreement calculation."""
        candidates = [
            CandidateLocation(candidate_id="c1", latitude=12.97, longitude=77.59, source="HISTORICAL_VISIT", probability=0.7),
            CandidateLocation(candidate_id="c2", latitude=12.98, longitude=77.60, source="HISTORICAL_VISIT", probability=0.2),
            CandidateLocation(candidate_id="c3", latitude=12.99, longitude=77.61, source="GEOCODER", probability=0.1),
        ]
        agreement = self.estimator._candidate_agreement(candidates)
        assert 0.0 <= agreement <= 1.0


class TestRecommendAction:
    """Test recommended action logic."""

    def test_high_confidence_direct(self):
        """Test high confidence recommends direct visit."""
        action = recommend_action(0.9, 50)
        assert action == RecommendedAction.VISIT_DIRECTLY

    def test_medium_confidence_verify(self):
        """Test medium confidence recommends verification."""
        action = recommend_action(0.7, 200)
        assert action == RecommendedAction.VERIFY_FIRST

    def test_low_confidence(self):
        """Test low confidence recommends low confidence action."""
        action = recommend_action(0.4, 1000)
        assert action == RecommendedAction.LOW_CONFIDENCE

    def test_high_confidence_large_radius(self):
        """Test high confidence but large radius recommends verification."""
        action = recommend_action(0.9, 200)
        assert action == RecommendedAction.VERIFY_FIRST