import pandas as pd

from evaluation.ps3_experiments import (
    _causal_artifact,
    _metric_for_predictions,
    summarize_errors,
)


def test_summarize_errors_reports_projected_distance_metrics():
    result = summarize_errors([10, 50, 100, 400], [50, 50, 100, 500])

    assert result.n == 4
    assert result.median_error_m == 75
    assert result.within_100m == 0.75
    assert result.coverage == 1.0


def test_metric_for_predictions_keeps_unmatched_predictions_out_of_coverage():
    frame = pd.DataFrame(
        {
            "address_id": ["a", "b"],
            "surveyed_x": [0.0, 100.0],
            "surveyed_y": [0.0, 0.0],
        }
    )
    predictions = pd.DataFrame(
        {
            "address_id": ["a"],
            "pred_x": [25.0],
            "pred_y": [0.0],
            "radius_m": [50.0],
        }
    )

    result = _metric_for_predictions(frame, predictions)

    assert result["n"] == 1
    assert result["coverage_rate"] == 0.5
    assert result["median_error_m"] == 25.0


def test_causal_artifact_refuses_missing_treatment_and_recovery():
    tables = {"visits": pd.DataFrame({"outcome": ["met_family"]})}

    result = _causal_artifact(tables)

    assert result["status"] == "not_estimable"
    assert "treatment/action/policy_arm" in result["required_columns"]
