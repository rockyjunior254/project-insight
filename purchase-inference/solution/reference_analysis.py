from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import statsmodels.api as sm
import statsmodels.formula.api as smf
from patsy import build_design_matrices

BASELINE_FORMULA = "observed_count ~ C(customer_id) + C(day_of_week)"
TREND_FORMULA = BASELINE_FORMULA + " + centered_day + C(customer_id):centered_day"
SELECTION_RULE = "select poisson_trend when trend_aic <= baseline_aic - 2.0; otherwise select poisson_baseline"
WALD_975 = 1.959963984540054


def read_transactions(data_dir: Path) -> pd.DataFrame:
    transactions = pd.read_json(data_dir / "retail_transactions.jsonl", lines=True)
    if transactions.empty:
        raise ValueError("The transaction release is empty.")
    transactions["customer_id"] = transactions["customer_id"].astype("int64")
    transactions["transaction_time"] = pd.to_datetime(
        transactions["transaction_time"], errors="raise"
    )
    if transactions[["customer_id", "transaction_time"]].isna().any().any():
        raise ValueError("Every record must have a customer ID and transaction time.")
    return transactions


def make_grid(transactions: pd.DataFrame) -> pd.DataFrame:
    observed = transactions.copy()
    observed["date"] = observed["transaction_time"].dt.normalize()
    customers = pd.DataFrame(
        {
            "customer_id": np.sort(observed["customer_id"].unique()),
            "exposure_customers": 1,
        }
    )
    dates = pd.DataFrame(
        {
            "date": pd.date_range(
                observed["date"].min(), observed["date"].max(), freq="D"
            )
        }
    )
    dates["_cross"] = 1
    customers["_cross"] = 1
    grid = dates.merge(customers, on="_cross").drop(columns="_cross")
    daily_counts = (
        observed.groupby(["date", "customer_id"], as_index=False)
        .size()
        .rename(columns={"size": "observed_count"})
    )
    grid = grid.merge(daily_counts, on=["date", "customer_id"], how="left")
    grid["observed_count"] = grid["observed_count"].fillna(0).astype("int64")
    grid["day_of_week"] = grid["date"].dt.dayofweek.astype("int64")
    day_index = (grid["date"] - grid["date"].min()).dt.days.astype(float)
    grid["centered_day"] = day_index - day_index.mean()
    grid["log_exposure"] = np.log(grid["exposure_customers"].astype(float))
    return grid.sort_values(["date", "customer_id"]).reset_index(drop=True)


def fit_models(grid: pd.DataFrame):
    baseline = smf.glm(
        BASELINE_FORMULA,
        data=grid,
        family=sm.families.Poisson(),
        offset=grid["log_exposure"],
    ).fit(maxiter=200, tol=1e-12)
    trend = smf.glm(
        TREND_FORMULA,
        data=grid,
        family=sm.families.Poisson(),
        offset=grid["log_exposure"],
    ).fit(maxiter=200, tol=1e-12)
    selected_name = (
        "poisson_trend"
        if trend.aic <= baseline.aic - 2.0
        else "poisson_baseline"
    )
    selected = trend if selected_name == "poisson_trend" else baseline

    def metrics(result: sm.GLMResultsWrapper) -> dict[str, float | int | bool]:
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

    coefficient_rows: list[dict[str, float | str]] = []
    for model_name, result in (
        ("poisson_baseline", baseline),
        ("poisson_trend", trend),
    ):
        intervals = result.conf_int(alpha=0.05)
        for term in result.params.index:
            estimate = float(result.params.loc[term])
            standard_error = float(result.bse.loc[term])
            coefficient_rows.append(
                {
                    "model": model_name,
                    "term": str(term),
                    "estimate": estimate,
                    "standard_error": standard_error,
                    "z_value": float(estimate / standard_error),
                    "p_value": float(result.pvalues.loc[term]),
                    "ci_lower": float(intervals.loc[term, 0]),
                    "ci_upper": float(intervals.loc[term, 1]),
                }
            )
    coefficients = (
        pd.DataFrame(coefficient_rows)
        .sort_values(["model", "term"])
        .reset_index(drop=True)
    )

    design = build_design_matrices(
        [selected.model.data.design_info], grid, return_type="dataframe"
    )[0]
    design_values = np.asarray(design, dtype=float)
    coefficients_array = np.asarray(selected.params, dtype=float)
    covariance = np.asarray(selected.cov_params(), dtype=float)
    linear_mean = design_values @ coefficients_array + grid["log_exposure"].to_numpy()
    linear_variance = np.einsum(
        "ij,jk,ik->i", design_values, covariance, design_values
    )
    linear_standard_error = np.sqrt(np.maximum(linear_variance, 0.0))
    predicted_count = np.exp(linear_mean)
    predicted_lower = np.exp(linear_mean - WALD_975 * linear_standard_error)
    predicted_upper = np.exp(linear_mean + WALD_975 * linear_standard_error)

    rates = grid[
        ["date", "customer_id", "exposure_customers", "observed_count"]
    ].copy()
    rates["model"] = selected_name
    rates["predicted_count"] = predicted_count
    rates["predicted_rate"] = predicted_count / rates["exposure_customers"]
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
    return coefficients, diagnostics, rates


def write_outputs(data_dir: Path, output_dir: Path) -> None:
    transactions = read_transactions(data_dir)
    grid = make_grid(transactions)
    coefficients, diagnostics, rates = fit_models(grid)
    output_dir.mkdir(parents=True, exist_ok=True)
    coefficient_columns = [
        "model",
        "term",
        "estimate",
        "standard_error",
        "z_value",
        "p_value",
        "ci_lower",
        "ci_upper",
    ]
    rate_columns = [
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
    pq.write_table(
        pa.Table.from_pandas(
            coefficients[coefficient_columns], preserve_index=False
        ),
        output_dir / "model_coefficients.parquet",
    )
    pq.write_table(
        pa.Table.from_pandas(rates[rate_columns], preserve_index=False),
        output_dir / "predicted_rates.parquet",
    )
    (output_dir / "model_diagnostics.json").write_text(
        json.dumps(diagnostics, sort_keys=True, indent=2, allow_nan=False) + "\n"
    )
    input_hash = hashlib.sha256(
        (data_dir / "retail_transactions.jsonl").read_bytes()
    ).hexdigest()
    validation = {
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
        "artifacts": [
            "model_coefficients.parquet",
            "model_diagnostics.json",
            "predicted_rates.parquet",
            "validation.json",
        ],
    }
    (output_dir / "validation.json").write_text(
        json.dumps(validation, sort_keys=True, indent=2) + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("/app/data"))
    parser.add_argument("--output", type=Path, default=Path("/app/output"))
    args = parser.parse_args()
    write_outputs(args.data, args.output)
