"""Candidate ranking model using LightGBM."""

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from uuid import uuid4

import lightgbm as lgb
import numpy as np
import joblib

from app.schemas import CandidateLocation, Prediction, PredictionEvidence, RecommendedAction
from config.settings import get_settings
from ml.visit_evidence import score_visit, ReliabilityScore
from ml.visit_integrity import detect_integrity, IntegrityScore

logger = logging.getLogger(__name__)


@dataclass
class RankingFeatures:
    """Feature vector for candidate ranking."""
    # Address similarity features
    address_similarity: float = 0.0
    landmark_similarity: float = 0.0
    locality_similarity: float = 0.0
    
    # Visit-based features
    distance_to_successful_visits: float = 0.0
    distance_to_failed_visits: float = 0.0
    number_of_supporting_visits: int = 0
    weighted_successful_visit_count: float = 0.0
    visit_integrity: float = 0.0
    gps_accuracy: float = 0.0
    dwell_time: float = 0.0
    trajectory_quality: float = 0.0
    
    # Account/cluster features
    nearby_account_support: int = 0
    commercial_geocoder_distance: float = 0.0
    place_cluster_support: int = 0
    agent_independence: float = 0.0
    
    # Source features (one-hot)
    source_historical: int = 0
    source_nearby: int = 0
    source_geocoder: int = 0
    source_landmark: int = 0
    source_locality: int = 0
    source_pincode: int = 0

    def to_array(self) -> np.ndarray:
        """Convert to numpy array for model."""
        return np.array([
            self.address_similarity,
            self.landmark_similarity,
            self.locality_similarity,
            self.distance_to_successful_visits,
            self.distance_to_failed_visits,
            float(self.number_of_supporting_visits),
            self.weighted_successful_visit_count,
            self.visit_integrity,
            self.gps_accuracy,
            self.dwell_time,
            self.trajectory_quality,
            float(self.nearby_account_support),
            self.commercial_geocoder_distance,
            float(self.place_cluster_support),
            self.agent_independence,
            float(self.source_historical),
            float(self.source_nearby),
            float(self.source_geocoder),
            float(self.source_landmark),
            float(self.source_locality),
            float(self.source_pincode),
        ], dtype=np.float32)

    @classmethod
    def feature_names(cls) -> list[str]:
        return [
            "address_similarity",
            "landmark_similarity",
            "locality_similarity",
            "distance_to_successful_visits",
            "distance_to_failed_visits",
            "number_of_supporting_visits",
            "weighted_successful_visit_count",
            "visit_integrity",
            "gps_accuracy",
            "dwell_time",
            "trajectory_quality",
            "nearby_account_support",
            "commercial_geocoder_distance",
            "place_cluster_support",
            "agent_independence",
            "source_historical",
            "source_nearby",
            "source_geocoder",
            "source_landmark",
            "source_locality",
            "source_pincode",
        ]


class CandidateRanker:
    """LightGBM-based candidate ranker."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.settings = get_settings()
        self.model: Optional[lgb.Booster] = None
        self.model_path = Path(self.config.get("model_path", self.settings.ranking_model_path))
        self.feature_version = self.config.get("feature_version", self.settings.feature_version)
        self._load_or_init_model()

    def _load_or_init_model(self):
        """Load existing model or initialize new one."""
        if self.model_path.exists():
            try:
                model = lgb.Booster(model_file=str(self.model_path))
                gains = model.feature_importance(importance_type="gain")
                if model.num_trees() <= 1 and not np.any(gains > 0):
                    raise ValueError("ranking model contains no feature splits")
                self.model = model
            except Exception as exc:
                logger.warning(
                    "Unable to load ranking model from %s; using heuristic scoring: %s",
                    self.model_path,
                    exc,
                )
                self.model = None
        else:
            self.model = None

    def train(self, X: np.ndarray, y: np.ndarray, 
              X_val: np.ndarray = None, y_val: np.ndarray = None) -> dict:
        """Train the ranking model."""
        params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "boosting_type": "gbdt",
            "num_leaves": 31,
            "learning_rate": 0.05,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 5,
            "min_data_in_leaf": 3,
            "min_sum_hessian_in_leaf": 1e-3,
            "feature_pre_filter": False,
            "verbose": -1,
            "random_state": 42,
            "n_estimators": 200,
        }
        
        train_data = lgb.Dataset(X, label=y, feature_name=RankingFeatures.feature_names())
        
        valid_sets = [train_data]
        valid_names = ["train"]
        
        if X_val is not None and y_val is not None:
            val_data = lgb.Dataset(X_val, label=y_val, feature_name=RankingFeatures.feature_names())
            valid_sets.append(val_data)
            valid_names.append("valid")
        
        self.model = lgb.train(
            params,
            train_data,
            valid_sets=valid_sets,
            valid_names=valid_names,
            num_boost_round=200,
            callbacks=[lgb.early_stopping(20), lgb.log_evaluation(50)] if X_val is not None else [],
        )
        
        # Save model
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        self.model.save_model(str(self.model_path))
        
        return {
            "best_iteration": self.model.best_iteration,
            "feature_importance": dict(zip(
                RankingFeatures.feature_names(),
                self.model.feature_importance(importance_type="gain")
            )),
        }

    def predict_proba(self, features: RankingFeatures) -> float:
        """Predict probability that candidate is correct."""
        if self.model is None:
            # Fallback heuristic
            return self._heuristic_score(features)
        
        X = features.to_array().reshape(1, -1)
        return float(self.model.predict(X, num_iteration=self.model.best_iteration)[0])

    def predict_batch(self, features_list: list[RankingFeatures]) -> np.ndarray:
        """Predict probabilities for multiple candidates."""
        if self.model is None:
            return np.array([self._heuristic_score(f) for f in features_list])
        
        X = np.array([f.to_array() for f in features_list])
        return self.model.predict(X, num_iteration=self.model.best_iteration)

    def _heuristic_score(self, features: RankingFeatures) -> float:
        """Heuristic scoring when model not trained."""
        score = 0.0
        
        # Address similarity
        score += features.address_similarity * 0.3
        score += features.landmark_similarity * 0.3
        score += features.locality_similarity * 0.1
        
        # Visit evidence
        if features.distance_to_successful_visits > 0:
            score += max(0, 1.0 - features.distance_to_successful_visits / 500) * 0.4
        if features.distance_to_failed_visits > 0:
            score -= min(0.3, features.distance_to_failed_visits / 1000)
        
        score += min(1.0, features.number_of_supporting_visits / 5) * 0.2
        score += min(1.0, features.weighted_successful_visit_count / 3) * 0.2
        score += features.visit_integrity * 0.15
        score += max(0, 1.0 - features.gps_accuracy / 500) * 0.1
        score += min(1.0, features.dwell_time / 300) * 0.1
        score += features.trajectory_quality * 0.1
        
        # Account support
        score += min(1.0, features.nearby_account_support / 3) * 0.2
        
        # Geocoder
        if features.commercial_geocoder_distance > 0:
            score += max(0, 1.0 - features.commercial_geocoder_distance / 1000) * 0.15
        
        # Cluster
        score += min(1.0, features.place_cluster_support / 3) * 0.15
        
        # Agent independence
        score += features.agent_independence * 0.1
        
        # Source prior
        if features.source_historical:
            score += 0.2
        elif features.source_nearby:
            score += 0.15
        elif features.source_geocoder:
            score += 0.1
        
        return max(0.0, min(1.0, score))

    def save(self, path: Optional[str] = None):
        """Save model to disk."""
        if self.model:
            save_path = Path(path) if path else self.model_path
            save_path.parent.mkdir(parents=True, exist_ok=True)
            self.model.save_model(str(save_path))


def extract_ranking_features(
    candidate: CandidateLocation,
    normalized_address,
    all_visits: list,
    all_accounts: list,
    place_clusters: list,
) -> RankingFeatures:
    """Extract ranking features for a candidate."""
    features = RankingFeatures()
    
    # Address similarity (would be computed from normalized address vs candidate)
    # Placeholder - in reality these come from the candidate object
    features.address_similarity = candidate.address_similarity
    features.landmark_similarity = candidate.landmark_similarity
    features.locality_similarity = candidate.locality_similarity
    
    # Visit features
    features.distance_to_successful_visits = candidate.distance_to_successful_visits or 999999
    features.distance_to_failed_visits = candidate.distance_to_failed_visits or 999999
    features.number_of_supporting_visits = candidate.supporting_visit_count
    features.weighted_successful_visit_count = candidate.weighted_successful_visit_count
    features.visit_integrity = candidate.visit_integrity
    features.gps_accuracy = candidate.gps_accuracy or 999
    features.dwell_time = candidate.dwell_time or 0
    features.trajectory_quality = candidate.trajectory_quality
    
    # Account/cluster
    features.nearby_account_support = candidate.nearby_account_support
    features.commercial_geocoder_distance = candidate.commercial_geocoder_distance or 999999
    features.place_cluster_support = candidate.place_cluster_support
    features.agent_independence = candidate.agent_independence
    
    # Source one-hot
    source = candidate.source
    source_val = source.value if hasattr(source, 'value') else source
    features.source_historical = 1 if source_val == "HISTORICAL_VISIT" else 0
    features.source_nearby = 1 if source_val == "NEARBY_ACCOUNT" else 0
    features.source_geocoder = 1 if source_val == "GEOCODER" else 0
    features.source_landmark = 1 if source_val == "LANDMARK" else 0
    features.source_locality = 1 if source_val == "LOCALITY" else 0
    features.source_pincode = 1 if source_val == "PINCODE" else 0
    
    return features


def rank_candidates(
    candidates: list[CandidateLocation],
    normalized_address,
    visits: list,
    accounts: list,
    clusters: list,
    ranker: CandidateRanker = None,
) -> list[CandidateLocation]:
    """Rank candidates and return sorted list with probabilities."""
    if ranker is None:
        ranker = CandidateRanker()
    
    # Extract features for all candidates
    features_list = [
        extract_ranking_features(c, normalized_address, visits, accounts, clusters)
        for c in candidates
    ]
    
    # Predict probabilities
    probabilities = ranker.predict_batch(features_list)
    
    # Attach probabilities and sort
    for candidate, prob in zip(candidates, probabilities):
        candidate.probability = prob
        candidate.score = prob  # Alias
    
    candidates.sort(key=lambda c: c.probability or 0, reverse=True)
    return candidates