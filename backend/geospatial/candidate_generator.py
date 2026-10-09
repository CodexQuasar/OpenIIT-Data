"""Candidate generation for geocoding pipeline."""

import math
from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

from app.schemas import (
    CandidateLocation, CandidateSource, NormalizedAddress, 
    Account, Visit, PlaceCluster
)
from config.settings import get_settings
from data.real_data import RealLandmark, RealLocality, get_dataset_loader
from rapidfuzz import fuzz


@dataclass
class CandidateGenerationContext:
    """Context for candidate generation."""
    normalized_address: NormalizedAddress
    historical_visits: list[Visit]
    nearby_accounts: list[Account]
    place_clusters: list[PlaceCluster]
    geocoder_results: list[CandidateLocation]


class CandidateGenerator:
    """Generates candidate locations for an address."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.settings = get_settings()
        self.candidate_count = self.config.get("candidate_count", self.settings.candidate_count)
        self.max_per_source = self.config.get("max_per_source", self.settings.max_candidates_per_source)
        self.dedup_radius = self.config.get("dedup_radius", self.settings.deduplication_radius_m)
        self.coordinate_system = self.config.get("coordinate_system", "wgs84")
        # Disable real dataset lookups (for testing with mock geocoder)
        self.disable_dataset_lookups = self.config.get("disable_dataset_lookups", False)
        # Load real dataset for landmark/locality/pincode lookups
        self._dataset_loader = None

    def _get_dataset_loader(self):
        """Lazy load dataset loader."""
        if self._dataset_loader is None:
            self._dataset_loader = get_dataset_loader()
            if not self._dataset_loader.landmarks:
                self._dataset_loader.load_all("train")
        return self._dataset_loader

    def generate_candidates(self, context: CandidateGenerationContext) -> list[CandidateLocation]:
        """Generate all candidates for an address."""
        all_candidates = []
        
        # 1. Historical successful visits
        historical = self._historical_visit_candidates(context)
        all_candidates.extend(historical)
        
        # 2. Nearby confirmed accounts
        nearby = self._nearby_account_candidates(context)
        all_candidates.extend(nearby)
        
        # 3. Place cluster centroids
        cluster = self._place_cluster_candidates(context)
        all_candidates.extend(cluster)
        
        # 4. Commercial geocoder results
        geocoder = self._geocoder_candidates(context)
        all_candidates.extend(geocoder)
        
        # 5. Landmark-based candidates (using real dataset)
        landmark = self._landmark_candidates(context)
        all_candidates.extend(landmark)
        
        # 6. Locality centroid (using real dataset)
        locality = self._locality_candidates(context)
        all_candidates.extend(locality)
        
        # 7. Pincode centroid (using real dataset)
        pincode = self._pincode_candidates(context)
        all_candidates.extend(pincode)
        
        # Deduplicate
        deduped = self._deduplicate(all_candidates)
        
        # Sort by source priority and limit
        final = self._select_top_candidates(deduped)
        
        return final

    def _historical_visit_candidates(self, context: CandidateGenerationContext) -> list[CandidateLocation]:
        """Generate candidates from historical successful visits."""
        candidates = []
        
        successful_visits = [
            v for v in context.historical_visits
            if v.outcome.value in ["SUCCESSFUL_CONTACT", "PARTIAL_CONTACT"]
        ]
        
        # Group by location (deduplicate nearby visits)
        visit_groups = self._group_nearby_visits(successful_visits)
        
        for i, group in enumerate(visit_groups[:self.max_per_source]):
            if not group:
                continue
            
            # Weighted centroid based on reliability
            lat, lon, weight = self._weighted_centroid(group)
            
            candidate = CandidateLocation(
                candidate_id=f"hist_{uuid4().hex[:8]}",
                latitude=lat,
                longitude=lon,
                source=CandidateSource.HISTORICAL_VISIT,
                source_reference=group[0].visit_id if group else None,
                supporting_visit_count=len(group),
                weighted_successful_visit_count=weight,
                visit_integrity=min(v.integrity_score or 1.0 for v in group),
                gps_accuracy=min(v.gps_accuracy or 999 for v in group),
                dwell_time=sum(v.dwell_time or 0 for v in group) / len(group) if group else None,
                trajectory_quality=self._avg_trajectory_quality(group),
            )
            candidates.append(candidate)
        
        return candidates

    def _nearby_account_candidates(self, context: CandidateGenerationContext) -> list[CandidateLocation]:
        """Generate candidates from nearby confirmed accounts."""
        candidates = []
        
        for account in context.nearby_accounts[:self.max_per_source]:
            if account.latitude is None or account.longitude is None:
                continue
            if account.confidence is None or account.confidence < 0.5:
                continue
            
            candidate = CandidateLocation(
                candidate_id=f"nearby_{uuid4().hex[:8]}",
                latitude=account.latitude,
                longitude=account.longitude,
                source=CandidateSource.NEARBY_ACCOUNT,
                source_reference=account.account_id,
                nearby_account_support=1,
                commercial_geocoder_distance=None,  # Will be filled later
                place_cluster_support=1 if account.place_cluster_id else 0,
            )
            candidates.append(candidate)
        
        return candidates

    def _place_cluster_candidates(self, context: CandidateGenerationContext) -> list[CandidateLocation]:
        """Generate candidates from place clusters."""
        candidates = []
        
        for cluster in context.place_clusters[:self.max_per_source]:
            if not cluster.account_ids:
                continue
            
            candidate = CandidateLocation(
                candidate_id=f"cluster_{uuid4().hex[:8]}",
                latitude=cluster.latitude,
                longitude=cluster.longitude,
                source=CandidateSource.LANDMARK,  # Using landmark as closest match
                source_reference=cluster.cluster_id,
                place_cluster_support=len(cluster.account_ids),
                landmark_similarity=0.8,  # Clusters based on landmark similarity
                visit_count=cluster.visit_count,
            )
            candidates.append(candidate)
        
        return candidates

    def _geocoder_candidates(self, context: CandidateGenerationContext) -> list[CandidateLocation]:
        """Generate candidates from geocoder results."""
        candidates = []
        
        for result in context.geocoder_results[:self.max_per_source]:
            candidate = CandidateLocation(
                candidate_id=f"geocoder_{uuid4().hex[:8]}",
                latitude=result.latitude,
                longitude=result.longitude,
                source=CandidateSource.GEOCODER,
                commercial_geocoder_distance=0,  # This IS the geocoder result
                gps_accuracy=result.gps_accuracy,
            )
            candidates.append(candidate)
        
        return candidates

    def _landmark_candidates(self, context: CandidateGenerationContext) -> list[CandidateLocation]:
        """Generate candidates from known landmarks in address using real dataset."""
        if self.disable_dataset_lookups:
            return []
        
        candidates = []
        
        # Extract landmarks from normalized address
        landmarks = [
            e.value for e in context.normalized_address.entities
            if e.entity_type == "LANDMARK"
        ]
        
        if context.normalized_address.landmark:
            landmarks.append(context.normalized_address.landmark)
        
        # Get landmarks from real dataset
        loader = self._get_dataset_loader()
        town_id = None
        # Try to get town_id from nearby accounts or clusters
        if context.nearby_accounts:
            town_id = context.nearby_accounts[0].town_id
        elif context.place_clusters:
            # Would need to get town from cluster
            pass
        
        dataset_landmarks = []
        if town_id:
            dataset_landmarks = loader.get_landmarks_for_town(town_id)
        else:
            dataset_landmarks = list(loader.landmarks.values())
        
        # Fuzzy match address landmarks to dataset landmarks
        for landmark_name in landmarks[:self.max_per_source]:
            best_match = None
            best_score = 0
            
            for ds_landmark in dataset_landmarks:
                score = fuzz.partial_ratio(landmark_name.lower(), ds_landmark.name.lower())
                if score > best_score and score >= 70:  # Threshold for match
                    best_score = score
                    best_match = ds_landmark
            
            if best_match:
                candidate = CandidateLocation(
                    candidate_id=f"landmark_{uuid4().hex[:8]}",
                    latitude=best_match.x,
                    longitude=best_match.y,
                    source=CandidateSource.LANDMARK,
                    source_reference=best_match.poi_id,
                    landmark_similarity=best_score / 100.0,
                    gps_accuracy=50.0,  # Landmark precision estimate
                )
                candidates.append(candidate)
        
        return candidates

    def _locality_candidates(self, context: CandidateGenerationContext) -> list[CandidateLocation]:
        """Generate candidate from locality centroid using real dataset."""
        if self.disable_dataset_lookups:
            return []
        
        candidates = []
        
        locality = context.normalized_address.locality
        city = context.normalized_address.city
        state = context.normalized_address.state
        
        if locality:
            # Get localities from real dataset
            loader = self._get_dataset_loader()
            town_id = None
            if context.nearby_accounts:
                town_id = context.nearby_accounts[0].town_id
            
            dataset_localities = []
            if town_id:
                dataset_localities = loader.get_localities_for_town(town_id)
            else:
                dataset_localities = list(loader.localities.values())
            
            # Fuzzy match
            best_match = None
            best_score = 0
            
            for ds_locality in dataset_localities:
                score = fuzz.partial_ratio(locality.lower(), ds_locality.locality_name.lower())
                if score > best_score and score >= 70:
                    best_score = score
                    best_match = ds_locality
            
            if best_match:
                candidate = CandidateLocation(
                    candidate_id=f"locality_{uuid4().hex[:8]}",
                    latitude=best_match.centroid_x,
                    longitude=best_match.centroid_y,
                    source=CandidateSource.LOCALITY,
                    source_reference=best_match.locality_id,
                    locality_similarity=best_score / 100.0,
                    gps_accuracy=500.0,  # Locality centroid precision
                )
                candidates.append(candidate)
        
        return candidates

    def _pincode_candidates(self, context: CandidateGenerationContext) -> list[CandidateLocation]:
        """Generate candidate from pincode centroid using real dataset."""
        if self.disable_dataset_lookups:
            return []
        
        candidates = []
        
        pincode = context.normalized_address.pincode
        
        if pincode:
            loader = self._get_dataset_loader()
            # Find locality with matching pincode
            best_match = None
            for ds_locality in loader.localities.values():
                if ds_locality.pincode == pincode:
                    best_match = ds_locality
                    break
            
            if best_match:
                candidate = CandidateLocation(
                    candidate_id=f"pincode_{uuid4().hex[:8]}",
                    latitude=best_match.centroid_x,
                    longitude=best_match.centroid_y,
                    source=CandidateSource.PINCODE,
                    source_reference=best_match.locality_id,
                    gps_accuracy=1000.0,  # Pincode centroid precision
                )
                candidates.append(candidate)
        
        return candidates

    def _group_nearby_visits(self, visits: list[Visit], radius_m: float = 50) -> list[list[Visit]]:
        """Group visits that are geographically close."""
        if not visits:
            return []
        
        groups = []
        used = set()
        
        for visit in visits:
            if visit.visit_id in used:
                continue
            
            group = [visit]
            used.add(visit.visit_id)
            
            for other in visits:
                if other.visit_id in used:
                    continue
                
                dist = self._haversine(
                    visit.latitude, visit.longitude,
                    other.latitude, other.longitude
                )
                
                if dist <= radius_m:
                    group.append(other)
                    used.add(other.visit_id)
            
            groups.append(group)
        
        # Sort groups by total reliability
        groups.sort(key=lambda g: sum(v.integrity_score or 0.5 for v in g), reverse=True)
        
        return groups

    def _weighted_centroid(self, visits: list[Visit]) -> tuple[float, float, float]:
        """Calculate weighted centroid of visits."""
        if not visits:
            return 0.0, 0.0, 0.0
        
        total_weight = 0.0
        weighted_lat = 0.0
        weighted_lon = 0.0
        
        for visit in visits:
            # Weight by integrity * outcome weight
            integrity = visit.integrity_score or 0.5
            outcome_weight = self._outcome_weight(visit.outcome)
            weight = integrity * outcome_weight
            
            weighted_lat += visit.latitude * weight
            weighted_lon += visit.longitude * weight
            total_weight += weight
        
        if total_weight == 0:
            # Simple average
            lat = sum(v.latitude for v in visits) / len(visits)
            lon = sum(v.longitude for v in visits) / len(visits)
            return lat, lon, float(len(visits))
        
        return weighted_lat / total_weight, weighted_lon / total_weight, total_weight

    def _outcome_weight(self, outcome) -> float:
        """Get weight for visit outcome."""
        weights = {
            "SUCCESSFUL_CONTACT": 1.0,
            "PARTIAL_CONTACT": 0.7,
            "FAILED_SEARCH": 0.1,
            "ADDRESS_NOT_TRACEABLE": 0.05,
            "WRONG_ADDRESS": 0.0,
            "BORROWER_MOVED": 0.1,
            "OTHER": 0.3,
        }
        return weights.get(outcome.value if hasattr(outcome, 'value') else outcome, 0.3)

    def _avg_trajectory_quality(self, visits: list[Visit]) -> float:
        """Calculate average trajectory quality."""
        qualities = []
        for visit in visits:
            if visit.trajectory and len(visit.trajectory) >= 2:
                # Simple quality: ratio of straight-line to actual path
                straight = self._haversine(
                    visit.trajectory[0].latitude, visit.trajectory[0].longitude,
                    visit.trajectory[-1].latitude, visit.trajectory[-1].longitude
                )
                actual = sum(
                    self._haversine(
                        visit.trajectory[i-1].latitude, visit.trajectory[i-1].longitude,
                        visit.trajectory[i].latitude, visit.trajectory[i].longitude
                    )
                    for i in range(1, len(visit.trajectory))
                )
                if actual > 0:
                    qualities.append(min(1.0, straight / actual))
        
        return sum(qualities) / len(qualities) if qualities else 0.5

    def _deduplicate(self, candidates: list[CandidateLocation]) -> list[CandidateLocation]:
        """Deduplicate candidates geographically."""
        if not candidates:
            return []
        
        # Sort by source priority
        source_priority = {
            CandidateSource.HISTORICAL_VISIT: 0,
            CandidateSource.NEARBY_ACCOUNT: 1,
            CandidateSource.LANDMARK: 2,
            CandidateSource.GEOCODER: 3,
            CandidateSource.LOCALITY: 4,
            CandidateSource.PINCODE: 5,
            CandidateSource.INTERPOLATION: 6,
        }
        
        candidates.sort(key=lambda c: source_priority.get(c.source, 99))
        
        deduped = []
        for candidate in candidates:
            # Check if close to any existing candidate
            is_duplicate = False
            for existing in deduped:
                dist = self._haversine(
                    candidate.latitude, candidate.longitude,
                    existing.latitude, existing.longitude
                )
                if dist <= self.dedup_radius:
                    is_duplicate = True
                    # Merge evidence
                    existing.supporting_visit_count += candidate.supporting_visit_count
                    existing.weighted_successful_visit_count += candidate.weighted_successful_visit_count
                    existing.nearby_account_support += candidate.nearby_account_support
                    existing.place_cluster_support += candidate.place_cluster_support
                    break
            
            if not is_duplicate:
                deduped.append(candidate)
        
        return deduped

    def _select_top_candidates(self, candidates: list[CandidateLocation]) -> list[CandidateLocation]:
        """Select top N candidates."""
        # Sort by evidence strength
        def evidence_score(c: CandidateLocation) -> float:
            score = 0.0
            score += c.supporting_visit_count * 2.0
            score += c.weighted_successful_visit_count * 1.5
            score += c.nearby_account_support * 1.5
            score += c.place_cluster_support * 1.0
            score += (1.0 - (c.gps_accuracy or 100) / 1000) * 0.5
            return score
        
        candidates.sort(key=evidence_score, reverse=True)
        return candidates[:self.candidate_count]

    def _haversine(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Haversine distance in meters."""
        if self.coordinate_system == "projected_xy":
            return math.hypot(lat2 - lat1, lon2 - lon1)

        R = 6371000
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c


def generate_candidates(
    normalized_address: NormalizedAddress,
    historical_visits: list[Visit],
    nearby_accounts: list[Account],
    place_clusters: list[PlaceCluster],
    geocoder_results: list[CandidateLocation],
    config: dict = None
) -> list[CandidateLocation]:
    """Convenience function to generate candidates."""
    generator = CandidateGenerator(config)
    context = CandidateGenerationContext(
        normalized_address=normalized_address,
        historical_visits=historical_visits,
        nearby_accounts=nearby_accounts,
        place_clusters=place_clusters,
        geocoder_results=geocoder_results,
    )
    return generator.generate_candidates(context)