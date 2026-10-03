from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import patsy
import pyarrow.parquet as pq
import pytest
import statsmodels.api as sm

OUTPUT_DIR = Path(os.getenv("APP_OUTPUT_DIR", "/app/output"))
DATA_DIR = Path(os.getenv("APP_DATA_DIR", "/tests/data"))
COEFFICIENTS = OUTPUT_DIR / "model_coefficients.parquet"
DIAGNOSTICS = OUTPUT_DIR / "model_diagnostics.json"
RATES = OUTPUT_DIR / "predicted_rates.parquet"
VALIDATION = OUTPUT_DIR / "validation.json"
DETERMINISM = OUTPUT_DIR / "determinism_report.json"
BASELINE = "observed_count ~ C(customer_id) + C(day_of_week)"
TREND = BASELINE + " + centered_day + C(customer_id):centered_day"
SELECTION_RULE = "select poisson_trend when trend_aic <= baseline_aic - 2.0; otherwise select poisson_baseline"
WALD_975 = 1.959963984540054
COEFFICIENT_COLUMNS = [
    "model",
    "term",
    "estimate",
    "standard_error",
    "z_value",
    "p_value",
    "ci_lower",
    "ci_upper",
]
RATE_COLUMNS = [
    "date",
    "customer_id",
    "exposure_customers",
    "observed_count",
    "model",
    "predicted_count",
    "predicted_rate",
    "rate_ci_lower",
    "rate_ci_upper",
]
SCIENTIFIC_ARTIFACTS = [
    "model_coefficients.parquet",
    "model_diagnostics.json",
    "predicted_rates.parquet",
    "validation.json",
]


def reconstruct_grid() -> tuple[pd.DataFrame, pd.DataFrame]:
    transactions = pd.read_json(DATA_DIR / "retail_transactions.jsonl", lines=True)
    transactions["customer_id"] = transactions["customer_id"].astype("int64")
    transactions["transaction_time"] = pd.to_datetime(
        transactions["transaction_time"], errors="raise"
    )
    transactions["date"] = transactions["transaction_time"].dt.normalize()
    customers = pd.DataFrame(
        {
            "customer_id": np.sort(transactions["customer_id"].unique()),
            "exposure_customers": 1,
        }
    )
    dates = pd.DataFrame(
        {
            "date": pd.date_range(
                transactions["date"].min(), transactions["date"].max(), freq="D"
            )
        }
    )
    dates["_join"] = 1
    customers["_join"] = 1
    grid = dates.merge(customers, on="_join").drop(columns="_join")
    counts = (
        transactions.groupby(["date", "customer_id"], as_index=False)
        .size()
        .rename(columns={"size": "observed_count"})
    )
    grid = grid.merge(counts, on=["date", "customer_id"], how="left")
    grid["observed_count"] = grid["observed_count"].fillna(0).astype("int64")
    grid["day_of_week"] = grid["date"].dt.dayofweek.astype("int64")
    day_index = (grid["date"] - grid["date"].min()).dt.days.astype(float)
    grid["centered_day"] = day_index - day_index.mean()
    grid["log_exposure"] = np.log(grid["exposure_customers"].astype(float))
    return (
        grid.sort_values(["date", "customer_id"]).reset_index(drop=True),
        transactions,
    )


def fit_independent_reference():
    grid, transactions = reconstruct_grid()
    response_base, design_base = patsy.dmatrices(
        BASELINE, grid, return_type="dataframe"
    )
    response_trend, design_trend = patsy.dmatrices(
        TREND, grid, return_type="dataframe"
    )
    baseline = sm.GLM(
        response_base,
        design_base,
        family=sm.families.Poisson(),
        offset=grid["log_exposure"],
    ).fit(maxiter=200, tol=1e-12)
    trend = sm.GLM(
        response_trend,
        design_trend,
        family=sm.families.Poisson(),
        offset=grid["log_exposure"],
    ).fit(maxiter=200, tol=1e-12)
    selected_name = (
        "poisson_trend"
        if trend.aic <= baseline.aic - 2.0
        else "poisson_baseline"
    )
    selected, selected_design = (
        (trend, design_trend)
        if selected_name == "poisson_trend"
        else (baseline, design_base)
    )

    def metrics(result):
        return {
            "log_likelihood": float(result.llf),
            "aic": float(result.aic),
            "bic_log_likelihood": float(result.bic_llf),
            "deviance": float(result.deviance),
            "pearson_chi_square": float(result.pearson_chi2),
            "overdispersion": float(result.pearson_chi2 / result.df_resid),
            "parameter_count": int(len(result.params)),
            "residual_degrees_of_freedom": float(result.df_resid),
            "converged": bool(result.converged),
        }

    coefficient_rows = []
    for model_name, result, design in (
        ("poisson_baseline", baseline, design_base),
        ("poisson_trend", trend, design_trend),
    ):
        intervals = result.conf_int(alpha=0.05)
        for index, term in enumerate(design.columns):
            estimate = float(result.params.iloc[index])
            standard_error = float(result.bse.iloc[index])
            coefficient_rows.append(
                {
                    "model": model_name,
                    "term": str(term),
                    "estimate": estimate,
                    "standard_error": standard_error,
                    "z_value": estimate / standard_error,
                    "p_value": float(result.pvalues.iloc[index]),
                    "ci_lower": float(intervals.iloc[index, 0]),
                    "ci_upper": float(intervals.iloc[index, 1]),
                }
            )
    coefficients = pd.DataFrame(coefficient_rows).sort_values(
        ["model", "term"]
    ).reset_index(drop=True)

    design_values = np.asarray(selected_design, dtype=float)
    covariance = np.asarray(selected.cov_params(), dtype=float)
    linear_mean = (
        design_values @ np.asarray(selected.params, dtype=float)
        + grid["log_exposure"].to_numpy()
    )
    linear_variance = np.einsum(
        "ij,jk,ik->i", design_values, covariance, design_values
    )
    linear_standard_error = np.sqrt(np.maximum(linear_variance, 0.0))
    predicted = np.exp(linear_mean)
    predicted_lower = np.exp(linear_mean - WALD_975 * linear_standard_error)
    predicted_upper = np.exp(linear_mean + WALD_975 * linear_standard_error)
    rates = grid[
        ["date", "customer_id", "exposure_customers", "observed_count"]
    ].copy()
    rates["model"] = selected_name
    rates["predicted_count"] = predicted
    rates["predicted_rate"] = predicted / rates["exposure_customers"]
    rates["rate_ci_lower"] = predicted_lower / rates["exposure_customers"]
    rates["rate_ci_upper"] = predicted_upper / rates["exposure_customers"]
    rates = rates.sort_values(["date", "customer_id"]).reset_index(drop=True)

    diagnostics = {
        "baseline": metrics(baseline),
        "trend": metrics(trend),
        "selected_model": selected_name,
        "selection": {
            "criterion": "AIC",
            "minimum_aic_improvement": 2.0,
            "rule": SELECTION_RULE,
            "baseline_aic": float(baseline.aic),
            "trend_aic": float(trend.aic),
            "aic_difference_trend_minus_baseline": float(trend.aic - baseline.aic),
        },
        "grid": {
            "analysis_unit": "calendar_day x customer_id",
            "customer_count": int(grid["customer_id"].nunique()),
            "observation_cells": int(len(grid)),
            "mean_observed_count": float(grid["observed_count"].mean()),
            "zero_count_fraction": float((grid["observed_count"] == 0).mean()),
        },
    }
    return coefficients, diagnostics, rates, grid, transactions


@pytest.fixture(scope="module")
def expected():
    return fit_independent_reference()


def test_required_scientific_artifacts_exist():
    for path in (COEFFICIENTS, DIAGNOSTICS, RATES, VALIDATION):
        assert path.is_file() and path.stat().st_size > 0, (
            f"Missing required scientific output: {path}"
        )


def test_coefficient_schema_and_values(expected):
    actual = pq.read_table(COEFFICIENTS).to_pandas()
    wanted = expected[0]
    assert list(actual.columns) == COEFFICIENT_COLUMNS
    actual = actual.sort_values(["model", "term"]).reset_index(drop=True)
    assert actual[["model", "term"]].equals(wanted[["model", "term"]])
    tolerances = {
        "estimate": 1e-6,
        "standard_error": 1e-6,
        "z_value": 1e-5,
        "p_value": 1e-5,
        "ci_lower": 1e-5,
        "ci_upper": 1e-5,
    }
    for column, tolerance in tolerances.items():
        assert np.allclose(
            actual[column], wanted[column], rtol=0.0, atol=tolerance
        ), column


def test_diagnostics_and_model_selection(expected):
    actual = json.loads(DIAGNOSTICS.read_text())
    wanted = expected[1]
    assert actual["selected_model"] == wanted["selected_model"]
    assert actual["selection"]["criterion"] == "AIC"
    assert actual["selection"]["minimum_aic_improvement"] == 2.0
    assert actual["selection"]["rule"] == SELECTION_RULE
    for model in ("baseline", "trend"):
        assert actual[model]["parameter_count"] == wanted[model]["parameter_count"]
        assert actual[model]["converged"] is True
        for key in (
            "log_likelihood",
            "aic",
            "bic_log_likelihood",
            "deviance",
            "pearson_chi_square",
            "overdispersion",
            "residual_degrees_of_freedom",
        ):
            assert abs(actual[model][key] - wanted[model][key]) <= 1e-5, (
                f"{model}.{key}"
            )
    for key in (
        "baseline_aic",
        "trend_aic",
        "aic_difference_trend_minus_baseline",
    ):
        assert abs(actual["selection"][key] - wanted["selection"][key]) <= 1e-5
    for key in (
        "customer_count",
        "observation_cells",
        "analysis_unit",
    ):
        assert actual["grid"][key] == wanted["grid"][key]
    for key in ("mean_observed_count", "zero_count_fraction"):
        assert abs(actual["grid"][key] - wanted["grid"][key]) <= 1e-12
    chooses_trend = (
        actual["selection"]["trend_aic"]
        <= actual["selection"]["baseline_aic"] - 2.0
    )
    assert (actual["selected_model"] == "poisson_trend") == chooses_trend


def test_rate_predictions_and_complete_customer_day_grid(expected):
    actual = pq.read_table(RATES).to_pandas()
    wanted = expected[2]
    assert list(actual.columns) == RATE_COLUMNS
    actual["date"] = pd.to_datetime(actual["date"])
    actual = actual.sort_values(["date", "customer_id"]).reset_index(drop=True)
    exact_columns = [
        "date",
        "customer_id",
        "exposure_customers",
        "observed_count",
        "model",
    ]
    pd.testing.assert_frame_equal(
        actual[exact_columns], wanted[exact_columns], check_dtype=False
    )
    for column in (
        "predicted_count",
        "predicted_rate",
        "rate_ci_lower",
        "rate_ci_upper",
    ):
        assert np.allclose(actual[column], wanted[column], rtol=0.0, atol=1e-5)
    assert (actual["predicted_rate"] > 0).all()
    assert (actual["rate_ci_lower"] > 0).all()
    assert (actual["rate_ci_upper"] >= actual["rate_ci_lower"]).all()


def test_validation_summary_matches_raw_release(expected):
    actual = json.loads(VALIDATION.read_text())
    _, diagnostics, _, grid, transactions = expected
    input_hash = hashlib.sha256(
        (DATA_DIR / "retail_transactions.jsonl").read_bytes()
    ).hexdigest()
    assert actual == {
        "status": "COMPLETED",
        "analysis_unit": "calendar_day x customer_id",
        "analysis_start_date": grid["date"].min().date().isoformat(),
        "analysis_end_date": grid["date"].max().date().isoformat(),
        "transaction_records_used": int(len(transactions)),
        "customer_cohorts": int(grid["customer_id"].nunique()),
        "observation_cells": int(len(grid)),
        "selected_model": diagnostics["selected_model"],
        "selection_threshold_aic": 2.0,
        "input_sha256": input_hash,
        "artifacts": SCIENTIFIC_ARTIFACTS,
    }


def test_verifier_collected_deterministic_rerun():
    assert DETERMINISM.is_file() and DETERMINISM.stat().st_size > 0
    report = json.loads(DETERMINISM.read_text())
    assert report["collector_version"] == 1
    assert report["entrypoint"] == "/app/src/pipeline/main.py"
    assert report["required_outputs"] == SCIENTIFIC_ARTIFACTS
    assert report["required_outputs_present_before"] is True
    assert report["required_outputs_present_after"] is True
    assert report["second_run"]["succeeded"] is True
    assert report["second_run"]["return_code"] == 0
    before = report["semantic_fingerprints_before"]
    after = report["semantic_fingerprints_after"]
    assert set(before) == set(SCIENTIFIC_ARTIFACTS)
    assert set(after) == set(SCIENTIFIC_ARTIFACTS)
    for name in SCIENTIFIC_ARTIFACTS:
        assert len(before[name]) == 64
        assert all(char in "0123456789abcdef" for char in before[name])
        assert len(after[name]) == 64
        assert all(char in "0123456789abcdef" for char in after[name])
    assert before == after
    assert report["scientific_outputs_unchanged"] is True
