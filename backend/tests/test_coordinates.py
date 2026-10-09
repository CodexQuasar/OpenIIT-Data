"""Tests for coordinate calculations."""

import math
import pytest
from ml.visit_evidence import VisitEvidenceScorer
from ml.visit_integrity import VisitIntegrityDetector
from app.schemas import Visit, VisitOutcome, TrajectoryPoint
from datetime import datetime, timedelta


class TestHaversine:
    """Test Haversine distance calculation."""

    def setup_method(self):
        self.scorer = VisitEvidenceScorer()

    def test_same_point(self):
        """Test distance between same point is zero."""
        dist = self.scorer._haversine(12.9716, 77.5946, 12.9716, 77.5946)
        assert dist == 0.0

    def test_known_distance(self):
        """Test known distance between two points."""
        # Bangalore to Mumbai is roughly 845km
        dist = self.scorer._haversine(12.9716, 77.5946, 19.0760, 72.8777)
        assert 800000 < dist < 900000  # Allow some tolerance

    def test_symmetry(self):
        """Test distance is symmetric."""
        d1 = self.scorer._haversine(12.9716, 77.5946, 19.0760, 72.8777)
        d2 = self.scorer._haversine(19.0760, 72.8777, 12.9716, 77.5946)
        assert abs(d1 - d2) < 1.0

    def test_small_distance(self):
        """Test small distance calculation."""
        dist = self.scorer._haversine(12.9716, 77.5946, 12.9717, 77.5947)
        assert 0 < dist < 50  # Should be small


class TestVisitEvidence:
    """Test visit evidence scoring."""

    def setup_method(self):
        self.scorer = VisitEvidenceScorer()

    def test_successful_visit_high_reliability(self):
        """Test successful visit with good metrics."""
        visit = Visit(
            visit_id="v1",
            account_id="a1",
            agent_id="agent1",
            timestamp=datetime.utcnow(),
            latitude=12.9716,
            longitude=77.5946,
            gps_accuracy=10.0,
            outcome=VisitOutcome.SUCCESSFUL_CONTACT,
            dwell_time=300,
        )
        result = self.scorer.calculate_reliability(visit)
        assert result.score > 0.7

    def test_failed_visit_low_reliability(self):
        """Test failed visit has lower reliability."""
        visit = Visit(
            visit_id="v2",
            account_id="a1",
            agent_id="agent1",
            timestamp=datetime.utcnow(),
            latitude=12.9716,
            longitude=77.5946,
            gps_accuracy=500.0,
            outcome=VisitOutcome.FAILED_SEARCH,
            dwell_time=30,
        )
        result = self.scorer.calculate_reliability(visit)
        assert result.score < 0.5

    def test_poor_gps_accuracy(self):
        """Test poor GPS accuracy reduces score."""
        visit = Visit(
            visit_id="v3",
            account_id="a1",
            agent_id="agent1",
            timestamp=datetime.utcnow(),
            latitude=12.9716,
            longitude=77.5946,
            gps_accuracy=1000.0,
            outcome=VisitOutcome.SUCCESSFUL_CONTACT,
            dwell_time=300,
        )
        result = self.scorer.calculate_reliability(visit)
        assert result.breakdown["gps_accuracy"] < 0.3

    def test_short_dwell_time(self):
        """Test short dwell time reduces score."""
        visit = Visit(
            visit_id="v4",
            account_id="a1",
            agent_id="agent1",
            timestamp=datetime.utcnow(),
            latitude=12.9716,
            longitude=77.5946,
            gps_accuracy=10.0,
            outcome=VisitOutcome.SUCCESSFUL_CONTACT,
            dwell_time=5,
        )
        result = self.scorer.calculate_reliability(visit)
        assert result.breakdown["dwell_time"] < 0.3


class TestVisitIntegrity:
    """Test visit integrity detection."""

    def setup_method(self):
        self.detector = VisitIntegrityDetector()

    def test_normal_visit(self):
        """Test normal visit passes integrity check."""
        visit = Visit(
            visit_id="v1",
            account_id="a1",
            agent_id="agent1",
            timestamp=datetime.utcnow(),
            latitude=12.9716,
            longitude=77.5946,
            gps_accuracy=10.0,
            outcome=VisitOutcome.SUCCESSFUL_CONTACT,
            dwell_time=300,
        )
        result = self.detector.analyze_visit(visit)
        assert result.score > 0.5

    def test_suspicious_short_visit(self):
        """Test suspiciously short visit flagged."""
        visit = Visit(
            visit_id="v2",
            account_id="a1",
            agent_id="agent1",
            timestamp=datetime.utcnow(),
            latitude=12.9716,
            longitude=77.5946,
            gps_accuracy=10.0,
            outcome=VisitOutcome.SUCCESSFUL_CONTACT,
            dwell_time=5,  # Suspiciously short
        )
        result = self.detector.analyze_visit(visit)
        # Score should be reduced from 1.0 due to short visit penalty
        assert result.score <= 0.8

    def test_repeated_coordinates(self):
        """Test repeated coordinates across accounts flagged."""
        visits = []
        for i in range(5):
            visits.append(Visit(
                visit_id=f"v{i}",
                account_id=f"a{i}",
                agent_id=f"agent{i}",
                timestamp=datetime.utcnow(),
                latitude=12.9716,
                longitude=77.5946,
                gps_accuracy=10.0,
                outcome=VisitOutcome.SUCCESSFUL_CONTACT,
                dwell_time=300,
            ))
        
        result = self.detector.analyze_visit(visits[0], visits)
        assert result.score < 0.7  # Should be flagged

    def test_impossible_speed(self):
        """Test impossible speed flagged."""
        now = datetime.utcnow()
        trajectory = [
            TrajectoryPoint(latitude=12.9716, longitude=77.5946, timestamp=now),
            TrajectoryPoint(latitude=13.0, longitude=77.6, timestamp=now + timedelta(seconds=10)),
        ]
        visit = Visit(
            visit_id="v3",
            account_id="a1",
            agent_id="agent1",
            timestamp=now,
            latitude=12.9716,
            longitude=77.5946,
            gps_accuracy=10.0,
            outcome=VisitOutcome.SUCCESSFUL_CONTACT,
            dwell_time=300,
            trajectory=trajectory,
        )
        result = self.detector.analyze_visit(visit)
        assert result.features.impossible_speed