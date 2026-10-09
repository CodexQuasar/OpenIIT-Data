"""Visit evidence reliability scoring."""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from statistics import mean, stdev

from app.schemas import Visit, TrajectoryPoint, VisitOutcome


@dataclass
class ReliabilityFeatures:
    """Features for visit reliability scoring."""
    gps_accuracy: Optional[float] = None
    dwell_time: Optional[int] = None
    visit_outcome: Optional[VisitOutcome] = None
    trajectory_length: Optional[float] = None
    straight_line_distance: Optional[float] = None
    trajectory_efficiency: Optional[float] = None
    number_of_gps_points: Optional[int] = None
    speed_statistics: dict = None
    stationary_duration: Optional[float] = None
    distance_from_known_account: Optional[float] = None
    agent_historical_reliability: Optional[float] = None
    repeat_visit_consistency: Optional[float] = None


@dataclass
class ReliabilityScore:
    """Visit reliability score with breakdown."""
    score: float
    features: ReliabilityFeatures
    breakdown: dict[str, float]
    flags: list[str]


class VisitEvidenceScorer:
    """Scores reliability of field visit evidence."""

    # Outcome weights
    OUTCOME_WEIGHTS = {
        VisitOutcome.SUCCESSFUL_CONTACT: 1.0,
        VisitOutcome.PARTIAL_CONTACT: 0.7,
        VisitOutcome.FAILED_SEARCH: 0.2,
        VisitOutcome.ADDRESS_NOT_TRACEABLE: 0.1,
        VisitOutcome.WRONG_ADDRESS: 0.05,
        VisitOutcome.BORROWER_MOVED: 0.1,
        VisitOutcome.OTHER: 0.3,
    }

    # GPS accuracy thresholds (meters)
    EXCELLENT_ACCURACY = 10.0
    GOOD_ACCURACY = 30.0
    FAIR_ACCURACY = 100.0
    POOR_ACCURACY = 500.0

    # Dwell time thresholds (seconds)
    MIN_MEANINGFUL_DWELL = 30
    GOOD_DWELL = 120
    EXCELLENT_DWELL = 300

    # Trajectory efficiency thresholds
    EXCELLENT_EFFICIENCY = 0.9
    GOOD_EFFICIENCY = 0.7
    FAIR_EFFICIENCY = 0.5

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.agent_reliability_cache: dict[str, float] = {}

    def calculate_reliability(self, visit: Visit, 
                              historical_visits: list[Visit] = None,
                              known_account_location: tuple[float, float] = None,
                              agent_reliability: float = None) -> ReliabilityScore:
        """Calculate visit reliability score."""
        features = self._extract_features(visit, historical_visits, known_account_location, agent_reliability)
        breakdown = {}
        flags = []

        # 1. GPS Accuracy Score (0-1)
        gps_score = self._score_gps_accuracy(features.gps_accuracy)
        breakdown["gps_accuracy"] = gps_score
        if gps_score < 0.3:
            flags.append("poor_gps_accuracy")

        # 2. Dwell Time Score (0-1)
        dwell_score = self._score_dwell_time(features.dwell_time)
        breakdown["dwell_time"] = dwell_score
        if dwell_score < 0.3:
            flags.append("short_dwell_time")

        # 3. Outcome Score (0-1)
        outcome_score = self._score_outcome(features.visit_outcome)
        breakdown["outcome"] = outcome_score
        if outcome_score < 0.3:
            flags.append("unfavorable_outcome")

        # 4. Trajectory Quality Score (0-1)
        traj_score = self._score_trajectory(features)
        breakdown["trajectory"] = traj_score
        if traj_score < 0.3:
            flags.append("poor_trajectory")

        # 5. Agent Reliability Score (0-1)
        agent_score = features.agent_historical_reliability or 0.5
        breakdown["agent_reliability"] = agent_score

        # 6. Consistency Score (0-1)
        consistency_score = features.repeat_visit_consistency or 0.5
        breakdown["consistency"] = consistency_score

        # 7. Distance from Known Location (if available)
        distance_score = 1.0
        if features.distance_from_known_account is not None:
            distance_score = self._score_distance(features.distance_from_known_account)
            breakdown["distance_consistency"] = distance_score
            if distance_score < 0.3:
                flags.append("far_from_known_location")

        # Weighted combination
        weights = {
            "gps_accuracy": 0.20,
            "dwell_time": 0.15,
            "outcome": 0.25,
            "trajectory": 0.15,
            "agent_reliability": 0.10,
            "consistency": 0.10,
            "distance_consistency": 0.05,
        }

        # Adjust weights if some features missing
        available_weights = {k: v for k, v in weights.items() if k in breakdown}
        if available_weights:
            total_weight = sum(available_weights.values())
            normalized_weights = {k: v/total_weight for k, v in available_weights.items()}
        else:
            normalized_weights = {}

        final_score = sum(breakdown[k] * normalized_weights.get(k, 0) for k in breakdown)
        
        # Clamp
        final_score = max(0.0, min(1.0, final_score))

        return ReliabilityScore(
            score=final_score,
            features=features,
            breakdown=breakdown,
            flags=flags
        )

    def _extract_features(self, visit: Visit,
                          historical_visits: list[Visit] = None,
                          known_account_location: tuple[float, float] = None,
                          agent_reliability: float = None) -> ReliabilityFeatures:
        """Extract features from visit."""
        features = ReliabilityFeatures()
        
        features.gps_accuracy = getattr(visit, 'gps_accuracy', None) or getattr(visit, 'gps_accuracy_m', None)
        features.dwell_time = getattr(visit, 'dwell_time', None) or getattr(visit, 'dwell_s', None)
        features.visit_outcome = visit.outcome
        features.number_of_gps_points = len(visit.trajectory) if hasattr(visit, 'trajectory') and visit.trajectory else None
        
        # Trajectory analysis
        if hasattr(visit, 'trajectory') and visit.trajectory and len(visit.trajectory) >= 2:
            features.trajectory_length = self._calculate_trajectory_length(visit.trajectory)
            features.straight_line_distance = self._haversine(
                visit.trajectory[0].latitude, visit.trajectory[0].longitude,
                visit.trajectory[-1].latitude, visit.trajectory[-1].longitude
            )
            if features.straight_line_distance > 0:
                features.trajectory_efficiency = features.straight_line_distance / features.trajectory_length
            
            features.speed_statistics = self._calculate_speed_stats(visit.trajectory)
            features.stationary_duration = self._calculate_stationary_duration(visit.trajectory)
        
        # Distance from known account location
        if known_account_location:
            features.distance_from_known_account = self._haversine(
                visit.latitude, visit.longitude,
                known_account_location[0], known_account_location[1]
            )
        
        # Agent reliability
        features.agent_historical_reliability = agent_reliability
        
        # Repeat visit consistency
        if historical_visits and len(historical_visits) > 1:
            features.repeat_visit_consistency = self._calculate_consistency(visit, historical_visits)
        
        return features

    def _score_gps_accuracy(self, accuracy: Optional[float]) -> float:
        """Score GPS accuracy."""
        if accuracy is None:
            return 0.4  # Unknown accuracy
        
        if accuracy <= self.EXCELLENT_ACCURACY:
            return 1.0
        elif accuracy <= self.GOOD_ACCURACY:
            return 0.8
        elif accuracy <= self.FAIR_ACCURACY:
            return 0.5
        elif accuracy <= self.POOR_ACCURACY:
            return 0.2
        else:
            return 0.1

    def _score_dwell_time(self, dwell: Optional[int]) -> float:
        """Score dwell time."""
        if dwell is None:
            return 0.4  # Unknown
        
        if dwell >= self.EXCELLENT_DWELL:
            return 1.0
        elif dwell >= self.GOOD_DWELL:
            return 0.8
        elif dwell >= self.MIN_MEANINGFUL_DWELL:
            return 0.5
        else:
            return 0.1  # Very short = suspicious

    def _score_outcome(self, outcome: Optional[VisitOutcome]) -> float:
        """Score visit outcome."""
        if outcome is None:
            return 0.3
        return self.OUTCOME_WEIGHTS.get(outcome, 0.3)

    def _score_trajectory(self, features: ReliabilityFeatures) -> float:
        """Score trajectory quality."""
        if features.trajectory_efficiency is None:
            return 0.4
        
        eff = features.trajectory_efficiency
        if eff >= self.EXCELLENT_EFFICIENCY:
            return 1.0
        elif eff >= self.GOOD_EFFICIENCY:
            return 0.8
        elif eff >= self.FAIR_EFFICIENCY:
            return 0.5
        else:
            return 0.2  # Very inefficient = wandering

    def _score_distance(self, distance_m: float) -> float:
        """Score distance from known location."""
        if distance_m <= 50:
            return 1.0
        elif distance_m <= 100:
            return 0.8
        elif distance_m <= 250:
            return 0.5
        elif distance_m <= 500:
            return 0.3
        else:
            return 0.1

    def _calculate_trajectory_length(self, trajectory: list[TrajectoryPoint]) -> float:
        """Calculate total trajectory length in meters."""
        total = 0.0
        for i in range(1, len(trajectory)):
            total += self._haversine(
                trajectory[i-1].latitude, trajectory[i-1].longitude,
                trajectory[i].latitude, trajectory[i].longitude
            )
        return total

    def _calculate_speed_stats(self, trajectory: list[TrajectoryPoint]) -> dict:
        """Calculate speed statistics from trajectory."""
        speeds = []
        for i in range(1, len(trajectory)):
            dt = (trajectory[i].timestamp - trajectory[i-1].timestamp).total_seconds()
            if dt > 0:
                dist = self._haversine(
                    trajectory[i-1].latitude, trajectory[i-1].longitude,
                    trajectory[i].latitude, trajectory[i].longitude
                )
                speed = dist / dt  # m/s
                speeds.append(speed)
        
        if not speeds:
            return {"mean": 0, "max": 0, "stdev": 0}
        
        return {
            "mean": mean(speeds),
            "max": max(speeds),
            "stdev": stdev(speeds) if len(speeds) > 1 else 0,
        }

    def _calculate_stationary_duration(self, trajectory: list[TrajectoryPoint]) -> float:
        """Calculate duration spent stationary (speed < 0.5 m/s)."""
        stationary = 0.0
        for i in range(1, len(trajectory)):
            dt = (trajectory[i].timestamp - trajectory[i-1].timestamp).total_seconds()
            if dt > 0:
                dist = self._haversine(
                    trajectory[i-1].latitude, trajectory[i-1].longitude,
                    trajectory[i].latitude, trajectory[i].longitude
                )
                speed = dist / dt
                if speed < 0.5:  # Less than 0.5 m/s = stationary
                    stationary += dt
        return stationary

    def _calculate_consistency(self, visit: Visit, historical: list[Visit]) -> float:
        """Calculate consistency with historical visits to same account."""
        if not historical:
            return 0.5
        
        # Find successful historical visits
        successful = [v for v in historical if v.outcome in [
            VisitOutcome.SUCCESSFUL_CONTACT, VisitOutcome.PARTIAL_CONTACT
        ]]
        
        if not successful:
            return 0.3
        
        # Calculate distances from this visit to successful visits
        distances = []
        for hist in successful:
            d = self._haversine(visit.latitude, visit.longitude, hist.latitude, hist.longitude)
            distances.append(d)
        
        # Consistency = inverse of median distance (normalized)
        median_dist = sorted(distances)[len(distances)//2]
        if median_dist <= 50:
            return 1.0
        elif median_dist <= 100:
            return 0.8
        elif median_dist <= 250:
            return 0.5
        elif median_dist <= 500:
            return 0.2
        else:
            return 0.1

    def _haversine(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate Haversine distance in meters."""
        R = 6371000  # Earth radius in meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        
        a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c


# Singleton instance
_scorer = None


def get_scorer(config: dict = None) -> VisitEvidenceScorer:
    """Get singleton scorer instance."""
    global _scorer
    if _scorer is None:
        _scorer = VisitEvidenceScorer(config)
    return _scorer


def score_visit(visit: Visit, historical_visits: list[Visit] = None,
                known_account_location: tuple = None,
                agent_reliability: float = None) -> ReliabilityScore:
    """Convenience function to score a visit."""
    return get_scorer().calculate_reliability(visit, historical_visits, known_account_location, agent_reliability)