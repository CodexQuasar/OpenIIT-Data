"""Analyze dataset and train the LightGBM ranker."""
import sys
import os
import json
sys.path.insert(0, '.')

from data.real_data import RealDatasetLoader
from ml.ranker import CandidateRanker, RankingFeatures, extract_ranking_features
from ml.address_normalizer import extract_entities, normalize_address
from ml.visit_evidence import score_visit
from data.real_models import map_outcome
import numpy as np

def main():
    print("=" * 60)
    print("DATASET ANALYSIS & MODEL TRAINING")
    print("=" * 60)
    
    # Load dataset
    print("\n[1] Loading dataset...")
    loader = RealDatasetLoader()
    loader.load_all('train')
    print(f"   Accounts: {len(loader.accounts)}")
    print(f"   Addresses: {len(loader.addresses)}")
    print(f"   Visits: {len(loader.field_visits)}")
    print(f"   Surveyed: {len(loader.surveyed_addresses)}")
    
    # Analyze outcomes
    print("\n[2] Analyzing visit outcomes...")
    from collections import Counter
    outcomes = Counter()
    for v_id, v in loader.field_visits.items():
        outcomes[v.outcome] += 1
    # Map to readable names
    outcome_names = {
        'met_borrower': 'SUCCESSFUL_CONTACT',
        'met_family': 'PARTIAL_CONTACT', 
        'locked_premises': 'FAILED_SEARCH',
        'address_not_traceable': 'ADDRESS_NOT_TRACEABLE',
        'no_such_person': 'ADDRESS_NOT_TRACEABLE',
        'cash_collected': 'SUCCESSFUL_CONTACT',
        'neighbour_says_shifted': 'FAILED_SEARCH'
    }
    readable_outcomes = {k: outcome_names.get(k, k) for k in outcomes}
    print(f"   Outcomes: {dict(outcomes)}")
    print(f"   Readable: {readable_outcomes}")
    
    # Analyze addresses
    print("\n[3] Analyzing addresses...")
    add_types = Counter()
    for a in loader.addresses:
        add_types[a.address_type] += 1
    print(f"   Address types: {dict(add_types)}")
    
    # Prepare training data for the ranker
    print("\n[3] Preparing training data...")
    
    # Get addresses with visits and surveyed ground truth
    addresses_with_visits = []
    visits_by_addr = {}
    for v_id, v in loader.field_visits.items():
        if v.address_id not in visits_by_addr:
            visits_by_addr[v.address_id] = []
        visits_by_addr[v.address_id].append(v)
    
    for addr_id in loader.surveyed_addresses:
        visits = visits_by_addr.get(addr_id, [])
        add = loader.addresses.get(addr_id)
        if add and add.address_text:
            outcomes_local = [v.outcome for v in visits]
            outcomes_local_counts = Counter(outcomes_local)

            surveyed = loader.surveyed_addresses[addr_id]
            addresses_with_visits.append({
                'address_id': addr_id,
                'address_text': add.address_text,
                'town_id': add.town_id,
                'outcomes': outcomes_local_counts,
                'visit_count': len(visits),
                'surveyed_x': surveyed.surveyed_x,
                'surveyed_y': surveyed.surveyed_y,
                'has_surveyed': True
            })
    
    print(f"   Addresses with visits + ground truth: {len(addresses_with_visits)}")
    
    # Prepare training features and labels
    X = []
    y = []
    
    for i, addr in enumerate(addresses_with_visits):
        # Normalize address
        normalized = extract_entities(addr['address_text'])
        
        # Get visits for this address
        visits = visits_by_addr.get(addr['address_id'], [])
        
        # Get baseline geocode
        baseline = loader.baseline_geocodes.get(addr['address_id'])
        
        # Create candidate locations
        candidates = []
        
        # 1. Historical visit candidate (using best successful visit)
        successful_visits = [v for v in visits if map_outcome(v.outcome) in ["SUCCESSFUL_CONTACT", "PARTIAL_CONTACT"]]
        if successful_visits:
            # Use the visit with best GPS accuracy as the candidate
            best_visit = max(successful_visits, key=lambda v: v.gps_accuracy_m if hasattr(v, 'gps_accuracy_m') else 0)
            candidates.append({
                'candidate_id': 'hist_best',
                'predicted_x': best_visit.checkin_x,
                'predicted_y': best_visit.checkin_y,
                'source': 'HISTORICAL_VISIT',
                'supporting_visit_count': len(successful_visits),
                'weighted_successful_visit_count': len(successful_visits),
                'visit_integrity': 0.8,
                'gps_accuracy': best_visit.gps_accuracy_m if hasattr(best_visit, 'gps_accuracy_m') else 50,
                'dwell_time': best_visit.dwell_s if hasattr(best_visit, 'dwell_s') else 0,
                'trajectory_quality': 0.7,
                'nearby_account_support': 0,
                'commercial_geocoder_distance': None,
                'place_cluster_support': 0,
                'agent_independence': 0.5,
            })
        
        # 2. Baseline geocode candidate
        if baseline:
            candidates.append({
                'candidate_id': 'baseline',
                'predicted_x': baseline.geocoder_x,
                'predicted_y': baseline.geocoder_y,
                'source': 'GEOCODER',
                'supporting_visit_count': 0,
                'weighted_successful_visit_count': 0,
                'visit_integrity': 1.0,
                'gps_accuracy': 100.0,
                'dwell_time': 0,
                'trajectory_quality': 0.5,
                'nearby_account_support': 0,
                'commercial_geocoder_distance': 0.0,
                'place_cluster_support': 0,
                'agent_independence': 1.0,
            })
        
        # 3. Locality centroid candidate (if available)
        town = loader.towns.get(addr['town_id'])
        if town:
            # Use town centroid as approximate location
            # Town centroids are in the local coordinate system
            locality = loader.localities.get(f"{addr['town_id']}-L01")
            if locality:
                candidates.append({
                    'candidate_id': 'locality_centroid',
                    'predicted_x': locality.centroid_x,
                    'predicted_y': locality.centroid_y,
                    'source': 'LOCALITY',
                    'supporting_visit_count': 0,
                    'weighted_successful_visit_count': 0,
                    'visit_integrity': 1.0,
                    'gps_accuracy': 500.0,
                    'dwell_time': 0,
                    'trajectory_quality': 0.3,
                    'nearby_account_support': 0,
                    'commercial_geocoder_distance': None,
                    'place_cluster_support': 0,
                    'agent_independence': 1.0,
                })
        
        # Extract features for each candidate and create labels
        # Label = 1 if candidate is within some distance of surveyed location, 0 otherwise
        dist_to_surveyed_best = np.sqrt((candidates[0]['predicted_x'] - addr['surveyed_x'])**2 + (candidates[0]['predicted_y'] - addr['surveyed_y'])**2) if candidates else 999
        dist_to_survey_baseline = np.sqrt((candidates[1]['predicted_x'] - addr['surveyed_x'])**2 + (candidates[1]['predicted_y'] - addr['surveyed_y'])**2) if len(candidates) > 1 else 999
        dist_to_survey_locality = np.sqrt((candidates[2]['predicted_x'] - addr['surveyed_x'])**2 + (candidates[2]['predicted_y'] - addr['surveyed_y'])**2) if len(candidates) > 2 else 999
        
        # Create one label: 1 if ANY candidate is within 250m of surveyed location
        best_label = 1.0 if min(dist_to_survey_best, dist_to_survey_baseline, dist_to_survey_locality) <= 250.0 else 0.0
        
        # Extract features for each candidate and add to training set
        for candidate in candidates:
            # Extract ranking features
            try:
                features = extract_ranking_features(
                    type('Candidate', (), candidate)(),
                    normalized,
                    visits_by_addr.get(addr['address_id'], []),
                    [],
                    []
                )
            except Exception as e:
                print(f"   Feature extraction error: {type(e).__name__}: {str(e)[:50]}")
                continue
            
            X.append(features.to_array())
            y.append(best_label)
    
    print(f"\n[4] Training data prepared: {len(X)} samples")
    if len(X) > 0:
        print(f"   Features shape: {np.array(X).shape}")
        print(f"   Labels shape: {np.array(y).shape}")
        print(f"   Positive rate (label=1): {np.mean(y):.2f}")
        
        # Train the ranker
        print("\n[5] Training LightGBM ranker...")
        ranker = CandidateRanker()
        
        # Split data - use first 80% for training, rest for validation
        split_idx = int(0.8 * len(X))
        X_train, X_val = np.array(X[:split_idx]), np.array(X[split_idx:])
        y_train, y_val = np.array(y[:split_idx]), np.array(y[split_idx:])
        
        try:
            result = ranker.train(X_train, y_train, X_val, y_val)
            print(f"   Training completed!")
            print(f"   Best iteration: {result['best_iteration']}")
            print(f"   Feature importance: {json.dumps(result['feature_importance'], indent=2)[:300]}")
            
            # Evaluate on validation set
            print("\n[6] Evaluating on validation set...")
            val_probs = ranker.predict_batch([type('Candidate', (), c)() for c in []])  # Placeholder
            # Use the model to predict
            val_X = np.array(X_val)
            val_probs = ranker.predict_batch([type('Candidate', (), {
                'candidate_id': 'val',
                'predicted_x': 0, 'predicted_y': 0,
                'source': 'HISTORICAL_VISIT',
                **{k: v for k, v in zip(RankingFeatures.feature_names(), row)}
            }) for row in X_val])
            
            # Simple metrics
            y_val_arr = np.array(y_val)
            train_pred = ranker.predict_batch([type('Candidate', (), c)() for c in X_train[:5]])  # Placeholder
            
            print(f"   Validation set size: {len(X_val)}")
            print(f"   Positive rate in val: {np.mean(y_val):.2f}")
            print(f"   Feature importance keys: {list(result['feature_importance'].keys())[:10]}")
            print(f"   Feature importance values (top 5): {dict(list(result['feature_importance'].items())[:5])}")
            
        except Exception as e:
            print(f"   Training error: {type(e).__name__}: {str(e)[:200]}")
            import traceback
            traceback.print_exc()
    else:
        print("   No training data prepared")
    
    print("\n" + "=" * 60)
    print("ANALYSIS COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    main()
PYEOF