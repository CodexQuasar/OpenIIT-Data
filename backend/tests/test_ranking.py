"""Tests for candidate ranking."""

import pytest
from ml.ranker import CandidateRanker, RankingFeatures, extract_ranking_features
from app.schemas import CandidateLocation, CandidateSource


class TestCandidateRanker:
    """Test candidate ranking model."""

    def setup_method(self):
        self.ranker = CandidateRanker()

    def test_heuristic_score_good_candidate(self):
        """Test heuristic scoring for good candidate."""
        features = RankingFeatures(
            address_similarity=0.9,
            landmark_similarity=0.8,
            locality_similarity=0.7,
            distance_to_successful_visits=50,
            number_of_supporting_visits=3,
            weighted_successful_visit_count=2.5,
            visit_integrity=0.9,
            gps_accuracy=10,
            dwell_time=300,
            trajectory_quality=0.9,
            nearby_account_support=2,
            place_cluster_support=1,
            agent_independence=0.8,
            source_historical=1,
        )
        score = self.ranker._heuristic_score(features)
        assert score > 0.7

    def test_heuristic_score_poor_candidate(self):
        """Test heuristic scoring for poor candidate."""
        features = RankingFeatures(
            address_similarity=0.1,
            landmark_similarity=0.1,
            locality_similarity=0.1,
            distance_to_successful_visits=1000,
            number_of_supporting_visits=0,
            weighted_successful_visit_count=0,
            visit_integrity=0.2,
            gps_accuracy=500,
            dwell_time=10,
            trajectory_quality=0.2,
            nearby_account_support=0,
            place_cluster_support=0,
            agent_independence=0.1,
            source_pincode=1,
        )
        score = self.ranker._heuristic_score(features)
        assert score < 0.4

    def test_feature_extraction(self):
        """Test feature extraction from candidate."""
        candidate = CandidateLocation(
            candidate_id="c1",
            latitude=12.9716,
            longitude=77.5946,
            source=CandidateSource.HISTORICAL_VISIT,
            address_similarity=0.8,
            landmark_similarity=0.7,
            locality_similarity=0.6,
            distance_to_successful_visits=100,
            number_of_supporting_visits=2,
            weighted_successful_visit_count=1.5,
            visit_integrity=0.8,
            gps_accuracy=20,
            dwell_time=200,
            trajectory_quality=0.8,
            nearby_account_support=1,
            place_cluster_support=0,
            agent_independence=0.7,
        )
        
        features = extract_ranking_features(candidate, None, [], [], [])
        assert features.address_similarity == 0.8
        assert features.source_historical == 1
        # number_of_supporting_visits comes from candidate.supporting_visit_count
        assert features.number_of_supporting_visits == candidate.supporting_visit_count

    def test_predict_proba_range(self):
        """Test probability prediction is in valid range."""
        features = RankingFeatures(
            address_similarity=0.5,
            landmark_similarity=0.5,
            locality_similarity=0.5,
        )
        prob = self.ranker.predict_proba(features)
        assert 0.0 <= prob <= 1.0

    def test_batch_prediction(self):
        """Test batch prediction."""
        features_list = [
            RankingFeatures(address_similarity=0.9, landmark_similarity=0.8),
            RankingFeatures(address_similarity=0.3, landmark_similarity=0.2),
        ]
        probs = self.ranker.predict_batch(features_list)
        assert len(probs) == 2
        assert all(0 <= p <= 1 for p in probs)