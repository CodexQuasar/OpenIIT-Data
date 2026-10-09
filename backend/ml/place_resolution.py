"""Place resolution for detecting shared physical locations across accounts."""

import math
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

import numpy as np
from rapidfuzz import fuzz
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler

from app.schemas import Account, NormalizedAddress, AddressEntity, PlaceCluster
from ml.address_normalizer import normalize_address
from ml.entity_extractor import extract_entities


@dataclass
class AccountFeatures:
    """Features for place clustering."""
    account_id: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address_text: str = ""
    normalized_address: str = ""
    landmarks: list[str] = field(default_factory=list)
    locality: Optional[str] = None
    pincode: Optional[str] = None
    building: Optional[str] = None
    street: Optional[str] = None
    cross: Optional[str] = None
    visit_count: int = 0
    successful_visits: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class PlaceClusterResult:
    """Result of place clustering."""
    clusters: list[PlaceCluster]
    account_cluster_map: dict[str, str]  # account_id -> cluster_id


class PlaceResolver:
    """Resolves place clusters from multiple accounts."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.eps_m = self.config.get("eps_m", 100.0)
        self.min_samples = self.config.get("min_samples", 2)
        self.text_similarity_threshold = self.config.get("text_similarity_threshold", 0.75)
        
        # For spatial clustering
        self.scaler = StandardScaler()
        
        # Embedding model (lazy load)
        self._embedding_model = None

    def resolve(self, accounts: list[Account], visits: list = None) -> PlaceClusterResult:
        """Resolve place clusters from accounts."""
        # Build features for each account
        features_list = self._build_features(accounts, visits)
        
        # Cluster using multiple signals
        cluster_labels = self._cluster_accounts(features_list)
        
        # Build clusters
        clusters = self._build_clusters(features_list, cluster_labels)
        
        # Map accounts to clusters
        account_cluster_map = {}
        for i, features in enumerate(features_list):
            if cluster_labels[i] >= 0:
                account_cluster_map[features.account_id] = clusters[cluster_labels[i]].cluster_id
        
        return PlaceClusterResult(clusters=clusters, account_cluster_map=account_cluster_map)

    def _build_features(self, accounts: list[Account], visits: list = None) -> list[AccountFeatures]:
        """Build feature vectors for each account."""
        features_list = []
        
        # Group visits by account
        visits_by_account = defaultdict(list)
        if visits:
            for visit in visits:
                if hasattr(visit, 'account_id'):
                    visits_by_account[visit.account_id].append(visit)
        
        for account in accounts:
            # Get normalized address
            norm_result = normalize_address(account.address)
            entities_result = extract_entities(account.address)
            
            # Extract landmarks from entities
            landmarks = [
                e.value for e in entities_result.entities 
                if e.entity_type == "LANDMARK"
            ]
            if entities_result.landmark:
                landmarks.append(entities_result.landmark)
            
            # Extract other entities
            building = next((e.value for e in entities_result.entities if e.entity_type == "BUILDING"), None)
            street = next((e.value for e in entities_result.entities if e.entity_type == "STREET"), None)
            cross = next((e.value for e in entities_result.entities if e.entity_type == "CROSS"), None)
            
            # Get visit info
            account_visits = visits_by_account.get(account.account_id, [])
            successful_visits = [
                (v.latitude, v.longitude) for v in account_visits
                if hasattr(v, 'outcome') and v.outcome in ["SUCCESSFUL_CONTACT", "PARTIAL_CONTACT"]
            ]
            
            # Use account location if available, else first successful visit
            lat, lon = account.latitude, account.longitude
            if lat is None and successful_visits:
                lat, lon = successful_visits[0]
            
            features = AccountFeatures(
                account_id=account.account_id,
                latitude=lat,
                longitude=lon,
                address_text=account.address,
                normalized_address=norm_result.normalized_address,
                landmarks=landmarks,
                locality=entities_result.locality or account.locality,
                pincode=entities_result.pincode or account.pincode,
                building=building,
                street=street,
                cross=cross,
                visit_count=len(account_visits),
                successful_visits=successful_visits,
            )
            features_list.append(features)
        
        return features_list

    def _cluster_accounts(self, features_list: list[AccountFeatures]) -> np.ndarray:
        """Cluster accounts using multiple similarity signals."""
        n = len(features_list)
        if n < 2:
            return np.array([0] * n)
        
        # Build similarity matrix
        similarity_matrix = np.zeros((n, n))
        
        for i in range(n):
            for j in range(i, n):
                sim = self._compute_similarity(features_list[i], features_list[j])
                similarity_matrix[i, j] = sim
                similarity_matrix[j, i] = sim
        
        # Convert to distance matrix
        distance_matrix = 1.0 - similarity_matrix
        np.fill_diagonal(distance_matrix, 0.0)
        
        # Use DBSCAN with precomputed distances
        clustering = DBSCAN(
            eps=1.0 - self.text_similarity_threshold,  # Approximate
            min_samples=self.min_samples,
            metric="precomputed",
        )
        
        labels = clustering.fit_predict(distance_matrix)
        
        # Also try spatial clustering for accounts with coordinates
        spatial_labels = self._spatial_clustering(features_list)
        
        # Combine: prefer spatial if available, else text
        final_labels = np.full(n, -1)
        for i in range(n):
            if spatial_labels[i] >= 0:
                final_labels[i] = spatial_labels[i]
            elif labels[i] >= 0:
                final_labels[i] = labels[i]
        
        return final_labels

    def _compute_similarity(self, f1: AccountFeatures, f2: AccountFeatures) -> float:
        """Compute combined similarity between two accounts."""
        similarities = []
        
        # 1. Spatial similarity (if both have coordinates)
        if f1.latitude and f2.latitude:
            dist = self._haversine(f1.latitude, f1.longitude, f2.latitude, f2.longitude)
            spatial_sim = math.exp(-dist / 200.0)  # Decay with distance
            similarities.append(("spatial", spatial_sim, 0.4))
        
        # 2. Landmark similarity
        if f1.landmarks and f2.landmarks:
            landmark_sim = self._set_similarity(f1.landmarks, f2.landmarks)
            similarities.append(("landmark", landmark_sim, 0.3))
        
        # 3. Address text similarity
        if f1.normalized_address and f2.normalized_address:
            text_sim = fuzz.token_set_ratio(f1.normalized_address, f2.normalized_address) / 100.0
            similarities.append(("text", text_sim, 0.2))
        
        # 4. Building similarity
        if f1.building and f2.building:
            building_sim = fuzz.ratio(f1.building.lower(), f2.building.lower()) / 100.0
            similarities.append(("building", building_sim, 0.25))
        
        # 5. Street similarity
        if f1.street and f2.street:
            street_sim = fuzz.ratio(f1.street.lower(), f2.street.lower()) / 100.0
            similarities.append(("street", street_sim, 0.15))
        
        # 6. Locality similarity
        if f1.locality and f2.locality:
            locality_sim = fuzz.ratio(f1.locality.lower(), f2.locality.lower()) / 100.0
            similarities.append(("locality", locality_sim, 0.1))
        
        # 7. Pincode match
        if f1.pincode and f2.pincode:
            pincode_sim = 1.0 if f1.pincode == f2.pincode else 0.0
            similarities.append(("pincode", pincode_sim, 0.05))
        
        # 8. Cross similarity
        if f1.cross and f2.cross:
            cross_sim = 1.0 if f1.cross == f2.cross else 0.0
            similarities.append(("cross", cross_sim, 0.1))
        
        # Weighted average
        if not similarities:
            return 0.0
        
        total_weight = sum(w for _, _, w in similarities)
        weighted_sum = sum(sim * w for _, sim, w in similarities)
        
        return weighted_sum / total_weight

    def _set_similarity(self, set1: list[str], set2: list[str]) -> float:
        """Calculate Jaccard-like similarity between two sets of strings."""
        if not set1 or not set2:
            return 0.0
        
        # Use fuzzy matching for set elements
        matches = 0
        for s1 in set1:
            for s2 in set2:
                if fuzz.ratio(s1.lower(), s2.lower()) > 85:
                    matches += 1
                    break
        
        return matches / max(len(set1), len(set2))

    def _spatial_clustering(self, features_list: list[AccountFeatures]) -> np.ndarray:
        """Cluster accounts by spatial proximity of successful visits."""
        # Collect all successful visit coordinates
        coords = []
        account_indices = []
        
        for i, f in enumerate(features_list):
            for lat, lon in f.successful_visits:
                coords.append([lat, lon])
                account_indices.append(i)
        
        if len(coords) < self.min_samples:
            return np.full(len(features_list), -1)
        
        coords = np.array(coords)
        
        # Convert to meters (approximate)
        # Use local projection around mean
        mean_lat = np.mean(coords[:, 0])
        mean_lon = np.mean(coords[:, 1])
        
        # Approximate meters per degree
        m_per_deg_lat = 111000
        m_per_deg_lon = 111000 * math.cos(math.radians(mean_lat))
        
        coords_m = coords.copy()
        coords_m[:, 0] = (coords[:, 0] - mean_lat) * m_per_deg_lat
        coords_m[:, 1] = (coords[:, 1] - mean_lon) * m_per_deg_lon
        
        # DBSCAN in meters
        clustering = DBSCAN(eps=self.eps_m, min_samples=self.min_samples, metric="euclidean")
        visit_labels = clustering.fit_predict(coords_m)
        
        # Map visit clusters back to accounts
        account_labels = np.full(len(features_list), -1)
        account_to_visit_clusters = defaultdict(set)
        
        for idx, label in zip(account_indices, visit_labels):
            if label >= 0:
                account_to_visit_clusters[idx].add(label)
        
        # Assign account to most common visit cluster
        for acct_idx, clusters in account_to_visit_clusters.items():
            if clusters:
                # Use most frequent cluster
                account_labels[acct_idx] = max(clusters, key=lambda c: sum(1 for l in visit_labels if l == c))
        
        return account_labels

    def _build_clusters(self, features_list: list[AccountFeatures], labels: np.ndarray) -> list[PlaceCluster]:
        """Build PlaceCluster objects from labels."""
        cluster_map = defaultdict(list)
        for i, label in enumerate(labels):
            if label >= 0:
                cluster_map[label].append(features_list[i])
        
        clusters = []
        for label, accounts in cluster_map.items():
            # Calculate cluster centroid
            lats = [a.latitude for a in accounts if a.latitude]
            lons = [a.longitude for a in accounts if a.longitude]
            
            if lats and lons:
                centroid_lat = sum(lats) / len(lats)
                centroid_lon = sum(lons) / len(lons)
            else:
                centroid_lat, centroid_lon = 0.0, 0.0
            
            # Collect landmarks
            all_landmarks = []
            for a in accounts:
                all_landmarks.extend(a.landmarks)
            unique_landmarks = list(set(all_landmarks))
            
            # Address variants
            address_variants = [a.address_text for a in accounts]
            
            # Total visits
            total_visits = sum(a.visit_count for a in accounts)
            
            # Confidence based on cluster size and visit count
            confidence = min(1.0, (len(accounts) * 0.2) + (total_visits * 0.05))
            
            cluster = PlaceCluster(
                cluster_id=f"cluster_{uuid4().hex[:8]}",
                latitude=centroid_lat,
                longitude=centroid_lon,
                account_ids=[a.account_id for a in accounts],
                landmarks=unique_landmarks,
                address_variants=address_variants,
                visit_count=total_visits,
                confidence=confidence,
            )
            clusters.append(cluster)
        
        return clusters

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


# Singleton instance
_resolver = None


def get_resolver(config: dict = None) -> PlaceResolver:
    """Get singleton resolver instance."""
    global _resolver
    if _resolver is None:
        _resolver = PlaceResolver(config)
    return _resolver


def resolve_places(accounts: list[Account], visits: list = None, config: dict = None) -> PlaceClusterResult:
    """Convenience function to resolve place clusters."""
    return get_resolver(config).resolve(accounts, visits)