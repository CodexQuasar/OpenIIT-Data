"""Visit integrity detection for fake/low-quality visits."""

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from statistics import mean, stdev

from app.schemas import Visit, TrajectoryPoint, VisitOutcome


@dataclass
class IntegrityFeatures:
    """Features for integrity detection."""
    # Coordinate-based
    identical_coord_count: int = 0
    identical_coord_accounts: int = 0
    coord_frequency_rank: float = 0.0
    
    # Agent-based
    agent_home_distance: Optional[float] = None
    agent_common_point_distance: Optional[float] = None
    agent_visit_pattern_score: float = 0.5
    
    # Temporal
    visit_duration_seconds: Optional[float] = None
    visit_time_anomaly: bool = False
    impossible_speed: bool = False
    max_speed_kmh: float = 0.0
    
    # Trajectory
    gps_jumps: int = 0
    trajectory_identical_count: int = 0
    trajectory_similarity: float = 0.0
    
    # Quality
    gps_accuracy: Optional[float] = None
    poor_accuracy_ratio: float = 0.0
    
    # Behavioral
    tea_shop_pattern: bool = False
    repeated_short_visits: int = 0


@dataclass
class IntegrityScore:
    """Integrity score with breakdown."""
    score: float  # 0-1, higher = more trustworthy
    features: IntegrityFeatures
    risk_factors: list[str]
    risk_level: str  # LOW, MEDIUM, HIGH, CRITICAL


class VisitIntegrityDetector:
    """Detects suspicious/fake visit evidence."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        
        # Thresholds
        self.same_coord_threshold = config.get("same_coord_threshold", 3) if config else 3
        self.speed_threshold_kmh = config.get("speed_threshold_kmh", 80.0) if config else 80.0
        self.min_visit_duration = config.get("min_visit_duration", 10) if config else 10
        self.gps_jump_threshold_m = config.get("gps_jump_threshold_m", 500) if config else 500
        self.trajectory_similarity_threshold = config.get("trajectory_similarity", 0.95) if config else 0.95
        
        # Caches for cross-visit analysis
        self.coordinate_counts: Counter = Counter()
        self.coordinate_accounts: defaultdict = defaultdict(set)
        self.agent_patterns: dict[str, list[Visit]] = defaultdict(list)
        self.common_meeting_points: dict[str, tuple[float, float]] = {}

    def analyze_visit(self, visit: Visit, 
                      all_visits: list[Visit] = None,
                      agent_home: tuple[float, float] = None) -> IntegrityScore:
        """Analyze a single visit for integrity issues."""
        # Update caches if all_visits provided
        if all_visits:
            self._update_caches(all_visits)
        
        features = self._extract_features(visit, agent_home)
        risk_factors = []
        
        # 1. Repeated identical coordinates across accounts
        if features.identical_coord_count >= self.same_coord_threshold:
            risk_factors.append(f"repeated_coordinates_{features.identical_coord_count}_accounts")
        elif features.identical_coord_count > 1:
            risk_factors.append(f"shared_coordinates_{features.identical_coord_count}_accounts")
        
        # 2. Agent home-like location
        if features.agent_home_distance is not None and features.agent_home_distance < 100:
            risk_factors.append("near_agent_home")
        
        # 3. Common meeting point (tea shop, etc.)
        if features.agent_common_point_distance is not None and features.agent_common_point_distance < 50:
            risk_factors.append("common_meeting_point")
            features.tea_shop_pattern = True
        
        # 4. Unusually short visit
        if features.visit_duration_seconds is not None and features.visit_duration_seconds < self.min_visit_duration:
            risk_factors.append("extremely_short_visit")
        
        # 5. Impossible movement speed
        if features.impossible_speed:
            risk_factors.append(f"impossible_speed_{features.max_speed_kmh:.0f}kmh")
        
        # 6. GPS jumps
        if features.gps_jumps > 0:
            risk_factors.append(f"gps_jumps_{features.gps_jumps}")
        
        # 7. Identical trajectories
        if features.trajectory_identical_count > 0:
            risk_factors.append(f"identical_trajectories_{features.trajectory_identical_count}")
        elif features.trajectory_similarity > self.trajectory_similarity_threshold:
            risk_factors.append(f"highly_similar_trajectory_{features.trajectory_similarity:.2f}")
        
        # 8. Poor GPS accuracy
        if features.gps_accuracy is not None and features.gps_accuracy > 500:
            risk_factors.append("poor_gps_accuracy")
        
        # 9. Repeated short visits by same agent
        if features.repeated_short_visits >= 3:
            risk_factors.append("pattern_short_visits")
        
        # 10. Visit timing anomaly
        if features.visit_time_anomaly:
            risk_factors.append("unusual_timing")
        
        # Calculate score
        score = self._calculate_score(features, risk_factors)
        risk_level = self._risk_level(score)
        
        return IntegrityScore(
            score=score,
            features=features,
            risk_factors=risk_factors,
            risk_level=risk_level
        )

    def _update_caches(self, visits: list[Visit]):
        """Update cross-visit analysis caches."""
        self.coordinate_counts.clear()
        self.coordinate_accounts.clear()
        self.agent_patterns.clear()
        
        for visit in visits:
            coord_key = f"{visit.latitude:.6f},{visit.longitude:.6f}"
            self.coordinate_counts[coord_key] += 1
            self.coordinate_accounts[coord_key].add(visit.account_id)
            self.agent_patterns[visit.agent_id].append(visit)
        
        # Identify common meeting points per agent
        self.common_meeting_points.clear()
        for agent_id, agent_visits in self.agent_patterns.items():
            coord_counter = Counter()
            for v in agent_visits:
                coord_key = f"{v.latitude:.6f},{v.longitude:.6f}"
                coord_counter[coord_key] += 1
            
            # Find most visited coordinate for this agent
            if coord_counter:
                most_common, count = coord_counter.most_common(1)[0]
                if count >= 3:  # Visited 3+ times
                    lat, lon = map(float, most_common.split(","))
                    self.common_meeting_points[agent_id] = (lat, lon)

    def _extract_features(self, visit: Visit, agent_home: tuple[float, float] = None) -> IntegrityFeatures:
        """Extract integrity features from visit."""
        features = IntegrityFeatures()
        
        coord_key = f"{visit.latitude:.6f},{visit.longitude:.6f}"
        
        # Coordinate frequency
        features.identical_coord_count = self.coordinate_counts.get(coord_key, 0)
        features.identical_coord_accounts = len(self.coordinate_accounts.get(coord_key, set()))
        
        # Rank of this coordinate frequency (0-1, higher = more common)
        if self.coordinate_counts:
            max_count = max(self.coordinate_counts.values())
            features.coord_frequency_rank = features.identical_coord_count / max_count
        
        # Agent home distance
        if agent_home:
            features.agent_home_distance = self._haversine(
                visit.latitude, visit.longitude, agent_home[0], agent_home[1]
            )
        
        # Common meeting point distance
        if visit.agent_id in self.common_meeting_points:
            mp = self.common_meeting_points[visit.agent_id]
            features.agent_common_point_distance = self._haversine(
                visit.latitude, visit.longitude, mp[0], mp[1]
            )
        
        # Visit duration
        if visit.dwell_time:
            features.visit_duration_seconds = visit.dwell_time
        elif visit.trajectory and len(visit.trajectory) >= 2:
            features.visit_duration_seconds = (
                visit.trajectory[-1].timestamp - visit.trajectory[0].timestamp
            ).total_seconds()
        
        # Timing anomaly (visit at unusual hours)
        if visit.timestamp:
            hour = visit.timestamp.hour
            if hour < 6 or hour > 22:  # Before 6am or after 10pm
                features.visit_time_anomaly = True
        
        # Trajectory analysis
        if visit.trajectory and len(visit.trajectory) >= 2:
            # GPS jumps
            for i in range(1, len(visit.trajectory)):
                dist = self._haversine(
                    visit.trajectory[i-1].latitude, visit.trajectory[i-1].longitude,
                    visit.trajectory[i].latitude, visit.trajectory[i].longitude
                )
                dt = (visit.trajectory[i].timestamp - visit.trajectory[i-1].timestamp).total_seconds()
                if dt > 0:
                    speed_kmh = (dist / dt) * 3.6
                    features.max_speed_kmh = max(features.max_speed_kmh, speed_kmh)
                    
                    if speed_kmh > self.speed_threshold_kmh:
                        features.impossible_speed = True
                    
                    if dist > self.gps_jump_threshold_m and dt < 60:  # Jump > 500m in < 1min
                        features.gps_jumps += 1
            
            # Check for identical trajectories with other visits by same agent
            agent_visits = self.agent_patterns.get(visit.agent_id, [])
            for other in agent_visits:
                if other.visit_id != visit.visit_id and other.trajectory:
                    sim = self._trajectory_similarity(visit.trajectory, other.trajectory)
                    if sim > 0.99:
                        features.trajectory_identical_count += 1
                    elif sim > features.trajectory_similarity:
                        features.trajectory_similarity = sim
        
        # GPS accuracy
        features.gps_accuracy = visit.gps_accuracy
        
        # Agent pattern: repeated short visits
        agent_visits = self.agent_patterns.get(visit.agent_id, [])
        short_count = sum(1 for v in agent_visits 
                         if v.dwell_time and v.dwell_time < self.min_visit_duration)
        features.repeated_short_visits = short_count
        
        return features

    def _calculate_score(self, features: IntegrityFeatures, risk_factors: list[str]) -> float:
        """Calculate integrity score from features and risk factors."""
        # Base score
        score = 1.0
        
        # Penalties for each risk factor
        penalties = {
            "repeated_coordinates": 0.3,
            "shared_coordinates": 0.15,
            "near_agent_home": 0.25,
            "common_meeting_point": 0.3,
            "extremely_short_visit": 0.2,
            "impossible_speed": 0.4,
            "gps_jumps": 0.15,
            "identical_trajectories": 0.35,
            "highly_similar_trajectory": 0.2,
            "poor_gps_accuracy": 0.15,
            "pattern_short_visits": 0.2,
            "unusual_timing": 0.1,
        }
        
        for factor in risk_factors:
            # Match penalty key
            for key, penalty in penalties.items():
                if factor.startswith(key):
                    score -= penalty
                    break
        
        # Additional continuous penalties
        if features.coord_frequency_rank > 0.5:
            score -= 0.1 * features.coord_frequency_rank
        
        if features.max_speed_kmh > self.speed_threshold_kmh:
            score -= min(0.3, (features.max_speed_kmh - self.speed_threshold_kmh) / 200)
        
        if features.gps_accuracy and features.gps_accuracy > 100:
            score -= min(0.2, (features.gps_accuracy - 100) / 1000)
        
        return max(0.0, min(1.0, score))

    def _risk_level(self, score: float) -> str:
        """Convert score to risk level."""
        if score >= 0.7:
            return "LOW"
        elif score >= 0.4:
            return "MEDIUM"
        elif score >= 0.2:
            return "HIGH"
        else:
            return "CRITICAL"

    def _trajectory_similarity(self, traj1: list[TrajectoryPoint], traj2: list[TrajectoryPoint]) -> float:
        """Calculate similarity between two trajectories (simplified)."""
        if not traj1 or not traj2:
            return 0.0
        
        # Simple comparison: start/end points and length
        start_dist = self._haversine(traj1[0].latitude, traj1[0].longitude, traj2[0].latitude, traj2[0].longitude)
        end_dist = self._haversine(traj1[-1].latitude, traj1[-1].longitude, traj2[-1].latitude, traj2[-1].longitude)
        
        len1 = len(traj1)
        len2 = len(traj2)
        len_diff = abs(len1 - len2) / max(len1, len2)
        
        # Similarity based on start/end proximity and length
        spatial_sim = 1.0 - min(1.0, (start_dist + end_dist) / 200)
        len_sim = 1.0 - len_diff
        
        return (spatial_sim + len_sim) / 2

    def _haversine(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate Haversine distance in meters."""
        R = 6371000
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c


# Singleton instance
_detector = None


def get_detector(config: dict = None) -> VisitIntegrityDetector:
    """Get singleton detector instance."""
    global _detector
    if _detector is None:
        _detector = VisitIntegrityDetector(config)
    return _detector


def detect_integrity(visit: Visit, all_visits: list[Visit] = None,
                     agent_home: tuple = None) -> IntegrityScore:
    """Convenience function to detect visit integrity."""
    return get_detector().analyze_visit(visit, all_visits, agent_home)