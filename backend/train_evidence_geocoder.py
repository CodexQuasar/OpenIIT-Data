"""Fit the evidence geocoder's parameters and report its accuracy.

The parameters (per-source error, visit reliability, confidence calibration)
are fitted on the train split by leave-one-account-out validation and written
to models/evidence_geocoder.json. Accuracy is then reported against surveyed
ground truth on every split; val and test are never used for fitting.

Usage:  python train_evidence_geocoder.py [--no-save]
"""

import argparse
import contextlib
import io
import math
import statistics
from collections import defaultdict

from data.real_data import RealDatasetLoader
from ml.calibration import recommend_action
from ml.evidence_geocoder import DEFAULT_PARAMS_PATH, SUCCESS_OUTCOMES, EvidenceGeocoder


def _load(split: str) -> RealDatasetLoader:
    loader = RealDatasetLoader()
    with contextlib.redirect_stdout(io.StringIO()):
        loader.load_all(split)
    return loader


def _summary(errors: list[float]) -> str:
    errors = sorted(errors)
    n = len(errors)
    if not n:
        return "n=0"
    within = lambda limit: sum(e <= limit for e in errors) / n
    return (f"n={n:4d}  median={errors[n // 2]:6.0f} m  p90={errors[min(n - 1, int(n * 0.9))]:6.0f} m  "
            f"<=100 m={within(100):4.0%}  <=250 m={within(250):4.0%}  <=500 m={within(500):4.0%}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-save", action="store_true", help="report only, do not write the parameter file")
    args = parser.parse_args()

    loaders = {split: _load(split) for split in ("train", "val", "test")}
    # An empty params dict skips the saved file and fits from scratch
    geocoder = EvidenceGeocoder(loaders["train"], params={})
    if not args.no_save:
        print(f"Saved {geocoder.save_params()}")
    else:
        print(f"Not saving (would write {DEFAULT_PARAMS_PATH})")
    print(f"Fitted on {geocoder.params['n_confirmed_addresses']} addresses with a confirmed visit location\n")

    pooled = []
    for split, loader in loaders.items():
        visits = defaultdict(list)
        for visit in loader.field_visits.values():
            visits[visit.address_id].append(visit)

        def predict(address_id, use_visits=True):
            if split == "train":
                if use_visits:
                    return geocoder.predict(address_id)
                address = loader.addresses[address_id]
                return geocoder.predict_for(
                    address.address_text, address.town_id, loader.baseline_geocodes.get(address_id), (),
                    exclude=geocoder._labels_by_account.get(address.account_id, frozenset()), use_visits=False)
            address = loader.addresses[address_id]
            return geocoder.predict_for(address.address_text, address.town_id, loader.baseline_geocodes.get(address_id),
                                        visits.get(address_id, ()), use_visits=use_visits)

        errors, baseline = [], []
        for address_id, surveyed in loader.surveyed_addresses.items():
            truth = (surveyed.surveyed_x, surveyed.surveyed_y)
            estimate = predict(address_id)
            if estimate:
                error = math.hypot(estimate.x - truth[0], estimate.y - truth[1])
                errors.append(error)
                pooled.append((estimate, error))
            geocode = loader.baseline_geocodes.get(address_id)
            if geocode:
                baseline.append(math.hypot(geocode.geocoder_x - truth[0], geocode.geocoder_y - truth[1]))

        cold = []
        for address_id, address_visits in visits.items():
            good = [v for v in address_visits if v.outcome in SUCCESS_OUTCOMES]
            if not good or loader.addresses[address_id].town_id not in loader.towns:
                continue
            estimate = predict(address_id, use_visits=False)
            if estimate:
                cold.append(math.hypot(estimate.x - statistics.median(v.checkin_x for v in good),
                                       estimate.y - statistics.median(v.checkin_y for v in good)))

        print(f"[{split}] surveyed ground truth ({len(loader.surveyed_addresses)} addresses)")
        print(f"    evidence geocoder    {_summary(errors)}")
        print(f"    commercial geocoder  {_summary(baseline)}")
        print("    cold start (own visits hidden, vs confirmed visit location)")
        print(f"    evidence geocoder    {_summary(cold)}")

    print("\nConfidence and recommended action, surveyed addresses of all splits")
    coverage = sum(error <= estimate.radius_m for estimate, error in pooled) / len(pooled)
    print(f"    truth inside the stated radius: {coverage:.0%} (target 80%)")
    by_action = defaultdict(list)
    for estimate, error in pooled:
        by_action[recommend_action(estimate.confidence, estimate.radius_m).value].append(error)
    for action, errors in sorted(by_action.items()):
        print(f"    {action:15s} {_summary(errors)}")


if __name__ == "__main__":
    main()
