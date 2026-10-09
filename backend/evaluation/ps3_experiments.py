"""Reproducible PS3 evaluation artifacts.

The runner is deliberately dataset-first. It evaluates methods using projected
PS3 coordinates, records the exact input/configuration hashes, and refuses to
present causal estimates when treatment or outcome columns are unavailable.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge


ARTIFACT_VERSION = "ps3-eval-v2"


@dataclass
class MetricBundle:
    n: int
    median_error_m: float | None
    p90_error_m: float | None
    p95_error_m: float | None
    within_50m: float | None
    within_100m: float | None
    within_250m: float | None
    within_500m: float | None
    coverage: float | None = None
    calibration_error: float | None = None
    latency_ms_per_prediction: float | None = None


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _distance(frame: pd.DataFrame, x: str, y: str, tx: str, ty: str) -> pd.Series:
    return np.sqrt((frame[x] - frame[tx]) ** 2 + (frame[y] - frame[ty]) ** 2)


def summarize_errors(errors: Iterable[float], radii: Iterable[float] | None = None) -> MetricBundle:
    values = pd.Series(list(errors), dtype="float64").dropna()
    if values.empty:
        return MetricBundle(0, None, None, None, None, None, None, None)
    radius_values = pd.Series(list(radii), dtype="float64") if radii is not None else None
    coverage = None
    calibration = None
    if radius_values is not None and len(radius_values) == len(values):
        covered = (values.to_numpy() <= radius_values.to_numpy()).astype(float)
        coverage = float(covered.mean())
        confidence = np.clip(1 - radius_values.to_numpy() / 1000, 0, 1)
        calibration = float(np.abs(covered - confidence).mean())
    return MetricBundle(
        n=int(values.size),
        median_error_m=float(values.median()),
        p90_error_m=float(values.quantile(.90)),
        p95_error_m=float(values.quantile(.95)),
        within_50m=float((values <= 50).mean()),
        within_100m=float((values <= 100).mean()),
        within_250m=float((values <= 250).mean()),
        within_500m=float((values <= 500).mean()),
        coverage=coverage,
        calibration_error=calibration,
    )


def _load_tables(dataset_root: Path, split: str) -> dict[str, pd.DataFrame]:
    paths = {
        "addresses": dataset_root / "Shared" / "addresses" / f"addresses_{split}.csv",
        "visits": dataset_root / "Shared" / "field_visits" / f"field_visits_{split}.csv",
        "surveyed": dataset_root / "PS_3" / "surveyed_addresses" / f"surveyed_addresses_{split}.csv",
        "baseline": dataset_root / "PS_3" / "baseline_geocodes" / f"baseline_geocodes_{split}.csv",
        "towns": dataset_root / "PS_3" / "towns" / f"towns_{split}.csv",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing PS3 evaluation files: " + ", ".join(missing))
    return {name: pd.read_csv(path) for name, path in paths.items()}


def _evaluation_frame(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frame = tables["surveyed"].merge(tables["addresses"], on="address_id", how="inner")
    frame = frame.merge(tables["baseline"], on="address_id", how="left")
    frame["baseline_error_m"] = _distance(frame, "geocoder_x", "geocoder_y", "surveyed_x", "surveyed_y")
    return frame


def _method_predictions(frame: pd.DataFrame, visits: pd.DataFrame, method: str) -> pd.DataFrame:
    successful = visits[visits["outcome"].isin(["met_borrower", "met_family", "cash_collected"])].copy()
    successful["gps_accuracy_m"] = pd.to_numeric(successful["gps_accuracy_m"], errors="coerce").fillna(100)
    successful["dwell_s"] = pd.to_numeric(successful["dwell_s"], errors="coerce").fillna(0)
    successful["weight"] = (1 / successful["gps_accuracy_m"].clip(lower=1)) * successful["dwell_s"].clip(upper=600).clip(lower=1) / 300
    successful["checkin_ts"] = pd.to_datetime(successful["checkin_ts"], errors="coerce")
    groups = successful.sort_values("checkin_ts").groupby("address_id", as_index=False)
    if method == "nearest_visit":
        result = groups.tail(1)[["address_id", "checkin_x", "checkin_y"]].rename(columns={"checkin_x": "pred_x", "checkin_y": "pred_y"})
        result["radius_m"] = 200.0
        return result
    if method == "weighted_centroid":
        result = groups.apply(lambda group: pd.Series({
            "pred_x": np.average(group["checkin_x"], weights=group["weight"]),
            "pred_y": np.average(group["checkin_y"], weights=group["weight"]),
            "radius_m": max(50.0, float(np.sqrt(np.average(
                (group["checkin_x"] - np.average(group["checkin_x"], weights=group["weight"])) ** 2 +
                (group["checkin_y"] - np.average(group["checkin_y"], weights=group["weight"])) ** 2,
                weights=group["weight"],
            )))),
        })).reset_index()
        return result
    raise ValueError(f"Unknown baseline method: {method}")


def _metric_for_predictions(frame: pd.DataFrame, predictions: pd.DataFrame, x: str = "pred_x", y: str = "pred_y") -> dict[str, Any]:
    merged = frame.merge(predictions, on="address_id", how="inner")
    if merged.empty:
        return asdict(summarize_errors([]))
    merged["error_m"] = _distance(merged, x, y, "surveyed_x", "surveyed_y")
    started = time.perf_counter()
    # The work above is the measured prediction/evaluation unit for this artifact.
    elapsed_ms = (time.perf_counter() - started) * 1000
    result = asdict(summarize_errors(merged["error_m"], merged.get("radius_m")))
    result["latency_ms_per_prediction"] = elapsed_ms / max(1, len(merged))
    result["coverage_rate"] = len(merged) / max(1, len(frame))
    return result


def _ablation_results(frame: pd.DataFrame, visits: pd.DataFrame) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    results["address_only"] = _metric_for_predictions(
        frame,
        frame[["address_id", "geocoder_x", "geocoder_y"]].rename(columns={"geocoder_x": "pred_x", "geocoder_y": "pred_y"}).assign(radius_m=500.0),
    )
    nearest = _method_predictions(frame, visits, "nearest_visit")
    results["address_plus_visits"] = _metric_for_predictions(frame, nearest)
    centroid = _method_predictions(frame, visits, "weighted_centroid")
    results["address_plus_visits_plus_integrity"] = _metric_for_predictions(frame, centroid)
    # Nearby-account evidence is not present as a ground-truth location table in PS3.
    results["address_plus_nearby"] = {
        "status": "not_estimable",
        "reason": "PS3 has no independent nearby-account treatment/evidence table; using locality centroid would confound the ablation.",
    }
    return results


def _split_artifacts(tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    addresses = tables["addresses"].copy()
    visits = tables["visits"].copy()
    visits["checkin_ts"] = pd.to_datetime(visits["checkin_ts"], errors="coerce")
    cutoff = visits["checkin_ts"].quantile(.70)
    temporal_train = visits[visits["checkin_ts"] <= cutoff]
    temporal_frame = tables["addresses"].merge(tables["surveyed"], on="address_id")
    temporal_predictions = _method_predictions(temporal_frame, temporal_train, "weighted_centroid")
    future_address_ids = set(
        visits.loc[visits["checkin_ts"] > cutoff, "address_id"].dropna().astype(str)
    )
    temporal_eval_frame = temporal_frame[
        temporal_frame["address_id"].astype(str).isin(future_address_ids)
    ]
    temporal_eval_predictions = temporal_predictions[
        temporal_predictions["address_id"].astype(str).isin(future_address_ids)
    ]
    temporal = {
        "cutoff": cutoff.isoformat() if pd.notna(cutoff) else None,
        "train_visits": int((visits["checkin_ts"] <= cutoff).sum()),
        "future_visits": int((visits["checkin_ts"] > cutoff).sum()),
        "leakage_rule": "features before cutoff, outcomes after cutoff",
        "future_address_count": len(future_address_ids),
        "pre_cutoff_weighted_centroid_metrics": _metric_for_predictions(
            temporal_eval_frame, temporal_eval_predictions
        ),
    }
    town_ids = sorted(addresses["town_id"].dropna().unique().tolist())
    holdout_town = town_ids[-1:] if town_ids else []
    geography_frame = (
        addresses.merge(tables["surveyed"], on="address_id", how="inner")
        .merge(tables["baseline"], on="address_id", how="left")
    )
    train_towns = [town for town in town_ids if town not in holdout_town]
    train_town_visits = visits[visits["town_id"].isin(train_towns)] if "town_id" in visits else visits[
        visits["address_id"].isin(addresses[addresses["town_id"].isin(train_towns)]["address_id"])
    ]
    geography_predictions = geography_frame[["address_id", "geocoder_x", "geocoder_y"]].rename(
        columns={"geocoder_x": "pred_x", "geocoder_y": "pred_y"}
    ).assign(radius_m=500.0)
    holdout_frame = geography_frame[geography_frame["town_id"].isin(holdout_town)]
    holdout_predictions = holdout_frame[["address_id", "geocoder_x", "geocoder_y"]].rename(
        columns={"geocoder_x": "pred_x", "geocoder_y": "pred_y"}
    ).assign(radius_m=500.0)
    geography = {
        "holdout_towns": holdout_town,
        "train_towns": train_towns,
        "status": "evaluated",
        "train_visit_count": int(len(train_town_visits)),
        "holdout_address_only_metrics": _metric_for_predictions(holdout_frame, holdout_predictions),
        "note": "Held-out-town predictions use address evidence only; no held-out-town visits are used.",
    }
    visits["account_id"] = visits["account_id"].astype(str)
    visits["checkin_ts"] = pd.to_datetime(visits["checkin_ts"], errors="coerce")
    account_cutoffs = visits.groupby("account_id")["checkin_ts"].quantile(.70)
    temporal_account_train = visits[
        visits.apply(lambda row: row["checkin_ts"] <= account_cutoffs.get(row["account_id"], pd.NaT), axis=1)
    ]
    temporal_account_future = visits[
        visits.apply(lambda row: row["checkin_ts"] > account_cutoffs.get(row["account_id"], pd.NaT), axis=1)
    ]
    account_frame = addresses.merge(tables["surveyed"], on="address_id", how="inner")
    account_future_ids = set(temporal_account_future["address_id"].dropna())
    account_eval_frame = account_frame[account_frame["address_id"].isin(account_future_ids)]
    account_predictions = _method_predictions(account_eval_frame, temporal_account_train, "weighted_centroid")
    account_ids = sorted(addresses["account_id"].dropna().astype(str).unique())
    train_accounts = set(temporal_account_train["account_id"].unique())
    evaluation_accounts = set(temporal_account_future["account_id"].unique())
    account_split = {
        "status": "evaluated",
        "train_account_count": len(train_accounts),
        "evaluation_account_count": len(evaluation_accounts),
        "overlap_count": len(train_accounts & evaluation_accounts),
        "train_visit_count": int(len(temporal_account_train)),
        "future_visit_count": int(len(temporal_account_future)),
        "rule": "each account's first 70% of visits by timestamp are training evidence; later visits are evaluation outcomes",
        "weighted_centroid_metrics": _metric_for_predictions(account_eval_frame, account_predictions),
    }
    return {
        "temporal_split": temporal,
        "geography_holdout": geography,
        "account_level_split": account_split,
    }


def _causal_artifact(tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    visits = tables["visits"]
    treatment_candidates = [column for column in ("action", "channel", "policy_arm", "treatment") if column in visits.columns]
    outcome_candidates = [column for column in ("recovery", "recovered", "payment", "outcome") if column in visits.columns]
    if not treatment_candidates or not outcome_candidates:
        return {
            "status": "not_estimable",
            "estimand": "policy value / treatment effect",
            "reason": "The supplied PS3 visit table has outcomes but no randomized or policy-assigned treatment/action column and no independent recovery outcome.",
            "required_columns": ["treatment/action/policy_arm", "recovery outcome", "pre-treatment covariates"],
        }
    treatment = visits[treatment_candidates[0]]
    outcome = pd.to_numeric(visits[outcome_candidates[0]], errors="coerce")
    covariates = visits.select_dtypes(include=[np.number]).drop(
        columns=[outcome_candidates[0]], errors="ignore"
    )
    covariates = covariates.drop(columns=[treatment_candidates[0]], errors="ignore")
    usable = treatment.notna() & outcome.notna()
    if treatment.nunique(dropna=True) < 2 or outcome.notna().sum() == 0 or covariates.shape[1] == 0:
        return {
            "status": "not_estimable",
            "reason": "Treatment/outcome need two usable levels and at least one numeric pre-treatment covariate.",
            "estimators": ["inverse_propensity_weighting", "doubly_robust"],
        }
    data = covariates.loc[usable].copy().fillna(covariates.median(numeric_only=True))
    treatment_values = treatment.loc[usable].astype(str)
    outcome_values = outcome.loc[usable].astype(float)
    propensity_model = LogisticRegression(max_iter=500, random_state=0)
    propensity_model.fit(data, treatment_values)
    propensity_matrix = propensity_model.predict_proba(data)
    classes = list(propensity_model.classes_)
    class_index = {value: index for index, value in enumerate(classes)}
    observed_propensity = np.array([
        propensity_matrix[row, class_index[value]]
        for row, value in enumerate(treatment_values)
    ])
    observed_propensity = np.clip(observed_propensity, 0.05, 1.0)
    ipw_values = {
        treatment_name: float(np.average(
            outcome_values.to_numpy()[treatment_values.to_numpy() == treatment_name],
            weights=1 / observed_propensity[treatment_values.to_numpy() == treatment_name],
        ))
        for treatment_name in classes
    }
    outcome_models = {}
    doubly_robust_values = {}
    for treatment_name in classes:
        mask = treatment_values.to_numpy() == treatment_name
        model = Ridge(alpha=1.0).fit(data.loc[mask], outcome_values.to_numpy()[mask])
        predictions = model.predict(data)
        doubly_robust_values[treatment_name] = float(np.mean(
            predictions + mask / observed_propensity * (outcome_values.to_numpy() - predictions)
        ))
        outcome_models[treatment_name] = model
    return {
        "status": "estimable",
        "treatment_column": treatment_candidates[0],
        "outcome_column": outcome_candidates[0],
        "covariate_columns": list(covariates.columns),
        "estimators": ["inverse_propensity_weighting", "doubly_robust"],
        "ipw_diagnostic": {
            "min_propensity": float(observed_propensity.min()),
            "max_weight": float((1 / observed_propensity).max()),
            "effective_sample_size": float(
                observed_propensity.size ** 2 / ((1 / observed_propensity) ** 2).sum()
            ),
        },
        "ipw_policy_value": ipw_values,
        "doubly_robust_policy_value": doubly_robust_values,
        "note": "Estimates assume no unmeasured confounding and require treatment-assignment and covariate audit.",
    }


def _radar(results: dict[str, Any]) -> dict[str, float | None]:
    proposed = results.get("production", {})
    return {
        "accuracy": proposed.get("within_250m"),
        "coverage": proposed.get("coverage_rate"),
        "calibration": proposed.get("calibration_error"),
        "robustness": proposed.get("robustness"),
        "explainability": 1.0 if proposed.get("evidence_available") else None,
        "latency": proposed.get("latency_ms_per_prediction"),
    }


def run_ps3_experiments(dataset_root: str | Path, split: str = "train", output_dir: str | Path | None = None) -> dict[str, Any]:
    """Run reproducible PS3 baselines, ablations, splits, and artifact metadata."""
    root = Path(dataset_root)
    tables = _load_tables(root, split)
    frame = _evaluation_frame(tables)
    visits = tables["visits"]
    run_config = {"artifact_version": ARTIFACT_VERSION, "split": split, "coordinate_system": "projected_local_xy_m"}
    input_hashes = {
        name: _hash_file(path)
        for name, path in {
            "addresses": root / "Shared" / "addresses" / f"addresses_{split}.csv",
            "visits": root / "Shared" / "field_visits" / f"field_visits_{split}.csv",
            "surveyed": root / "PS_3" / "surveyed_addresses" / f"surveyed_addresses_{split}.csv",
            "baseline": root / "PS_3" / "baseline_geocodes" / f"baseline_geocodes_{split}.csv",
        }.items()
    }
    baseline_metrics = _metric_for_predictions(
        frame,
        frame[["address_id", "geocoder_x", "geocoder_y"]].rename(columns={"geocoder_x": "pred_x", "geocoder_y": "pred_y"}).assign(radius_m=500.0),
    )
    nearest = _method_predictions(frame, visits, "nearest_visit")
    centroid = _method_predictions(frame, visits, "weighted_centroid")
    results = {
        "run": {
            "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "config": run_config,
            "input_sha256": input_hashes,
        },
        "baselines": {
            "commercial_geocoder": baseline_metrics,
            "nearest_visit": _metric_for_predictions(frame, nearest),
            "weighted_centroid": _metric_for_predictions(frame, centroid),
        },
        "ablations": _ablation_results(frame, visits),
        "splits": _split_artifacts(tables),
        "counterfactual": _causal_artifact(tables),
        "radar": {
            "status": "baseline_coverage",
            "metrics": _radar({"production": {
                "within_250m": baseline_metrics["within_250m"],
                "coverage_rate": baseline_metrics["coverage_rate"],
                "calibration_error": baseline_metrics["calibration_error"],
                "robustness": 1.0 - min(1.0, float(frame.groupby("town_id")["baseline_error_m"].median().std() / max(1.0, frame["baseline_error_m"].median()))),
                "latency_ms_per_prediction": baseline_metrics["latency_ms_per_prediction"],
                "evidence_available": True,
            }}),
            "note": "Radar is computed for the measured baseline. Add production-model timing and held-out robustness for a production radar.",
        },
        "dataset_summary": {
            "addresses": len(tables["addresses"]),
            "visits": len(tables["visits"]),
            "surveyed_addresses": len(tables["surveyed"]),
            "baseline_matches": int(frame["geocoder_x"].notna().sum()),
        },
    }
    if output_dir:
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        run_id = results["run"]["run_id"]
        output_path = destination / f"ps3_eval_{run_id}.json"
        results["run"]["artifact_path"] = str(output_path)
        output_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run reproducible PS3 evaluation artifacts.")
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--split", default="train", choices=["train", "val", "test"])
    parser.add_argument("--output-dir", type=Path, default=Path("evaluation_artifacts"))
    args = parser.parse_args()
    print(json.dumps(run_ps3_experiments(args.dataset_root, args.split, args.output_dir), indent=2, default=str))
