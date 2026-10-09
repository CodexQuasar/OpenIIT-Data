"""Train the LightGBM candidate ranker on real dataset."""
import sys
import os
import json
import hashlib
import re
import numpy as np
from pathlib import Path

# Add backend to path
sys.path.insert(0, os.path.dirname(__file__))

from data.real_data import RealDatasetLoader
from ml.ranker import CandidateRanker, RankingFeatures, extract_ranking_features
from ml.address_normalizer import normalize_address, get_normalizer
# map_outcome is defined locally below
from data.real_models import SurveyedAddress
import lightgbm as lgb

def main():
    print("=" * 60)
    print("TRAINING LIGHTGBM CANDIDATE RANKER")
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
    outcome_names = {
        'met_borrower': 'SUCCESSFUL_CONTACT',
        'met_family': 'PARTIAL_CONTACT',
        'locked_premises': 'FAILED_SEARCH',
        'address_not_traceable': 'ADDRESS_NOT_TRACEABLE',
        'no_such_person': 'ADDRESS_NOT_TRACEABLE',
        'cash_collected': 'SUCCESSFUL_CONTACT',
        'neighbour_says_shifted': 'FAILED_SEARCH'
    }
    readable = {k: outcome_names.get(k, k) for k in outcomes}
    print(f"   Outcomes: {dict(outcomes)}")
    print(f"   Readable: {readable}")
    
    # Build visits by address
    print("\n[3] Building visits index...")
    visits_by_addr = {}
    for v_id, v in loader.field_visits.items():
        if v.address_id not in visits_by_addr:
            visits_by_addr[v.address_id] = []
        visits_by_addr[v.address_id].append(v)
    
    # Build baseline geocodes
    print("\n[4] Building baseline geocodes...")
    baseline_by_addr = {}
    for addr_id, bc in loader.baseline_geocodes.items():
        baseline_by_addr[addr_id] = bc
    
    # Prepare training data
    print("\n[5] Preparing training data...")
    addresses_with_visits = []
    all_account_ids = {
        address.account_id
        for address in loader.addresses.values()
        if getattr(address, "account_id", None)
    }
    train_account_ids = {
        account_id
        for account_id in all_account_ids
        if int(hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:8], 16) % 5 != 0
    }
    evaluation_account_ids = all_account_ids - train_account_ids
    if train_account_ids & evaluation_account_ids:
        raise RuntimeError("Account split leakage detected before ranker training")
    print(
        f"   Account split: {len(train_account_ids)} train / "
        f"{len(evaluation_account_ids)} evaluation; overlap=0"
    )
    
    for addr_id in loader.surveyed_addresses:
        visits = visits_by_addr.get(addr_id, [])
        add = loader.addresses.get(addr_id)
        if not add or add.account_id not in train_account_ids:
            continue
        if not add or not add.address_text:
            continue
        
        surveyed = loader.surveyed_addresses[addr_id]
        surveyed_x = surveyed.surveyed_x
        surveyed_y = surveyed.surveyed_y
        
        # Normalize address
        normalized = normalize_address(add.address_text)
        
        # Count outcome categories
        outcomes_local = Counter()
        for v in visits:
            outcomes_local[map_outcome(v.outcome)] += 1
        
        addresses_with_visits.append({
            'address_id': addr_id,
            'address_text': add.address_text,
            'surveyed_x': surveyed_x,
            'surveyed_y': surveyed_y,
            'visits': visits,
            'normalized': normalized,
            'outcomes': outcomes_local,
            'visit_count': len(visits),
            'baseline': baseline_by_addr.get(addr_id),
        })
    
    print(f"   Addresses with visits + ground truth: {len(addresses_with_visits)}")
    
    if len(addresses_with_visits) == 0:
        print("   No addresses with visits + ground truth! Check dataset.")
        return
    
    # Create candidates and extract features
    print("\n[6] Creating candidates and extracting features...")
    
    X = []
    y = []
    feature_names = RankingFeatures.feature_names()

    class _Candidate:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
    
    # Use every eligible address. The account-level split above prevents
    # evaluation accounts from leaking into the training data.
    for i, addr in enumerate(addresses_with_visits):
        # Create candidate locations
        candidates = []
        normalized = addr['normalized']
        visits = addr['visits']
        baseline = addr['baseline']
        surveyed_x = addr['surveyed_x']
        surveyed_y = addr['surveyed_y']
        
        # 1. Add every successful historical visit as an independent example.
        successful_visits = [v for v in visits if map_outcome(v.outcome) in ["SUCCESSFUL_CONTACT", "PARTIAL_CONTACT"]]
        for visit in successful_visits:
            candidates.append(_Candidate(
                candidate_id=f"hist_{visit.visit_id}",
                predicted_x=visit.checkin_x,
                predicted_y=visit.checkin_y,
                source='HISTORICAL_VISIT',
                supporting_visit_count=len(successful_visits),
                weighted_successful_visit_count=len(successful_visits),
                visit_integrity=0.8,
                gps_accuracy=visit.gps_accuracy_m,
                dwell_time=visit.dwell_s,
                trajectory_quality=0.7,
                nearby_account_support=0,
                commercial_geocoder_distance=None,
                place_cluster_support=0,
                agent_independence=0.5,
                address_similarity=0.6,
                landmark_similarity=0.4,
                locality_similarity=0.5,
                distance_to_successful_visits=0.0,
                distance_to_failed_visits=999999.0,
            ))
            
            # 2. Baseline geocode candidate.
            if baseline:
                candidates.append(_Candidate(
                    candidate_id='baseline',
                    predicted_x=baseline.geocoder_x,
                    predicted_y=baseline.geocoder_y,
                    source='GEOCODER',
                    supporting_visit_count=0,
                    weighted_successful_visit_count=0,
                    visit_integrity=1.0,
                    gps_accuracy=100.0,
                    dwell_time=0,
                    trajectory_quality=0.5,
                    nearby_account_support=0,
                    commercial_geocoder_distance=0.0,
                    place_cluster_support=0,
                    agent_independence=1.0,
                    address_similarity=0.5,
                    landmark_similarity=0.3,
                    locality_similarity=0.4,
                    distance_to_successful_visits=999999.0,
                    distance_to_failed_visits=999999.0,
                ))
        
        # 3. Add every known locality centroid in the address town.
        for locality in loader.get_localities_for_town(add.town_id):
            candidates.append(_Candidate(
                candidate_id=f"locality_{locality.locality_id}",
                predicted_x=locality.centroid_x,
                predicted_y=locality.centroid_y,
                source='LOCALITY',
                supporting_visit_count=0,
                weighted_successful_visit_count=0,
                visit_integrity=1.0,
                gps_accuracy=500.0,
                dwell_time=0,
                trajectory_quality=0.3,
                nearby_account_support=0,
                commercial_geocoder_distance=None,
                place_cluster_support=0,
                agent_independence=1.0,
                address_similarity=0.2,
                landmark_similarity=0.0,
                locality_similarity=0.8,
                distance_to_successful_visits=999999.0,
                distance_to_failed_visits=999999.0,
            ))

        # 4. Add pincode centroids as the same fallback candidates used at runtime.
        pincode_match = re.search(r"\b\d{6}\b", addr['address_text'])
        pincode = pincode_match.group(0) if pincode_match else None
        if pincode:
            for locality in loader.localities.values():
                if locality.pincode != pincode:
                    continue
                candidates.append(_Candidate(
                    candidate_id=f"pincode_{locality.locality_id}",
                    predicted_x=locality.centroid_x,
                    predicted_y=locality.centroid_y,
                    source='PINCODE',
                    supporting_visit_count=0,
                    weighted_successful_visit_count=0,
                    visit_integrity=1.0,
                    gps_accuracy=1000.0,
                    dwell_time=0,
                    trajectory_quality=0.2,
                    nearby_account_support=0,
                    commercial_geocoder_distance=None,
                    place_cluster_support=0,
                    agent_independence=1.0,
                    address_similarity=0.1,
                    landmark_similarity=0.0,
                    locality_similarity=0.3,
                    distance_to_successful_visits=999999.0,
                    distance_to_failed_visits=999999.0,
                ))
        
        # Calculate distances to surveyed location
        for candidate in candidates:
            dist = np.sqrt((candidate.predicted_x - surveyed_x)**2 + (candidate.predicted_y - surveyed_y)**2)
            label = 1.0 if dist <= 250.0 else 0.0
            
            # Extract ranking features
            try:
                features = extract_ranking_features(
                    candidate,
                    addr['normalized'],
                    visits_by_addr.get(addr['address_id'], []),
                    [],  # accounts
                    []   # clusters
                )
                X.append(features.to_array())
                y.append(label)
            except Exception as e:
                print(f"   Feature extraction error for addr {addr['address_id']}: {type(e).__name__}: {str(e)[:100]}")
                # Create fallback features
                try:
                    fr = RankingFeatures()
                    X.append(fr.to_array())
                    y.append(label)
                except:
                    pass
        
        if (i + 1) % 50 == 0:
            print(f"   Processed {i+1}/{len(addresses_with_visits)} addresses...")
    
    print(f"\n[7] Training data prepared: {len(X)} samples")
    if len(X) > 0:
        X_arr = np.array(X)
        y_arr = np.array(y)
        print(f"   Features shape: {X_arr.shape}")
        print(f"   Labels shape: {y_arr.shape}")
        print(f"   Positive rate (label=1): {np.mean(y_arr):.2f}")
        print(f"   Positive samples: {np.sum(y_arr):.0f} / {len(y_arr)}")
        print(f"   Negative samples: {len(y_arr) - np.sum(y_arr):.0f} / {len(y_arr)}")
        
        # Shuffle before splitting so validation is not determined by CSV order.
        print("\n[8] Splitting data...")
        rng = np.random.default_rng(42)
        order = rng.permutation(len(X_arr))
        split_idx = int(0.8 * len(X_arr))
        train_idx, val_idx = order[:split_idx], order[split_idx:]
        X_train, X_val = X_arr[train_idx], X_arr[val_idx]
        y_train, y_val = y_arr[train_idx], y_arr[val_idx]
        
        print(f"   Train: {len(X_train)} samples ({np.mean(y_train):.2f} positive rate)")
        print(f"   Val: {len(X_val)} samples ({np.mean(y_val):.2f} positive rate)")
        
        # Train the ranker
        print("\n[9] Training LightGBM ranker...")
        ranker = CandidateRanker()
        
        try:
            result = ranker.train(
                X_train, y_train,
                X_val, y_val
            )
            print(f"   [OK] Training completed!")
            print(f"   Best iteration: {result['best_iteration']}")
            print(f"   Feature importance:")
            fi = result['feature_importance']
            # Print top 10
            sorted_fi = sorted(fi.items(), key=lambda x: x[1], reverse=True)
            for name, importance in sorted_fi[:10]:
                print(f"     {name}: {importance:.2f}")
            
            # Save model info
            model_path = ranker.model_path
            model_path.parent.mkdir(parents=True, exist_ok=True)
            ranker.save(str(model_path))
            print(f"   Model saved to: {model_path}")
            
            # Evaluate on validation set
            print("\n[10] Evaluating on validation set...")
            # Use the trained model directly on validation features
            val_probs = ranker.model.predict(X_val, num_iteration=ranker.model.best_iteration)
            
            y_val_arr = y_val
            # Convert probabilities to binary predictions at 0.5 threshold
            val_preds = (val_probs > 0.5).astype(int)
            
            from sklearn.metrics import precision_score, recall_score, f1_score, confusion_matrix
            
            precision = precision_score(y_val_arr, val_preds, zero_division=0)
            recall = recall_score(y_val_arr, val_preds, zero_division=0)
            f1 = f1_score(y_val_arr, val_preds, zero_division=0)
            tn, fp, fn, tp = confusion_matrix(y_val_arr, val_preds).ravel()
            
            print(f"   Validation metrics:")
            print(f"     Precision: {precision:.3f}")
            print(f"     Recall: {recall:.3f}")
            print(f"     F1: {f1:.3f}")
            print(f"     True Positives: {tp}, False Positives: {fp}")
            print(f"     True Negatives: {tn}, False Negatives: {fn}")
            
            # Calculate calibration - what probability corresponds to actual accuracy
            print(f"\n[11] Calibration analysis...")
            # Group by probability buckets
            prob_buckets = {}
            for p, t in zip(val_probs, y_val_arr):
                bucket = int(p * 10)  # 0.0-1.0 in steps of 0.1
                if bucket not in prob_buckets:
                    prob_buckets[bucket] = {'correct': 0, 'total': 0}
                prob_buckets[bucket]['total'] += 1
                if p >= 0.5 == t == 1:  # simplified calibration check
                    prob_buckets[bucket]['correct'] += 1
            
            for bucket in sorted(prob_buckets.keys()):
                b = prob_buckets[bucket]
                acc = b['correct'] / b['total'] if b['total'] > 0 else 0
                avg_p = (bucket / 10 + (bucket + 1) / 10) / 2
                print(f"   Bucket {avg_p:.1f}: accuracy={acc:.2f}, avg_prob={avg_p:.2f}, count={b['total']}")
            
        except Exception as e:
            print(f"   [ERROR] Training error: {type(e).__name__}: {str(e)[:200]}")
            import traceback
            traceback.print_exc()
    else:
        print("   No training data prepared!")
    
    print("\n" + "=" * 60)
    print("TRAINING COMPLETE")
    print("=" * 60)

def map_outcome(outcome_str):
    """Map outcome string to standard label."""
    outcome_map = {
        'met_borrower': 'SUCCESSFUL_CONTACT',
        'met_family': 'PARTIAL_CONTACT',
        'locked_premises': 'FAILED_SEARCH',
        'address_not_traceable': 'ADDRESS_NOT_TRACEABLE',
        'no_such_person': 'ADDRESS_NOT_TRACEABLE',
        'cash_collected': 'SUCCESSFUL_CONTACT',
        'neighbour_says_shifted': 'FAILED_SEARCH'
    }
    return outcome_map.get(outcome_str, outcome_str)

if __name__ == "__main__":
    main()