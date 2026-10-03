# Inference and Calibration of Purchase-Intensity Dynamics from Retail Transactions

Implement a reproducible scientific analysis in `/app/src/pipeline/main.py`. Read the supplied `retail_transactions.jsonl` from `/app/data` and write the required outputs under `/app/output`.

The release contains row-level retail records for 20 curated customers over 385 calendar days. Treat each supplied JSONL row as one recorded purchase line and each `customer_id` as its own fixed analysis cohort. The release is a selected case study, not a probability sample; report rates conditional on these customers and do not interpret them as population estimates. The old generated country and segment labels are not part of this release because they were deterministic assignments rather than observed customer attributes.

Construct a complete calendar-day × customer grid from the earliest through latest `transaction_time`, including zero-count cells. For each customer, set `exposure_customers` to 1 and `observed_count` to the number of supplied rows on that date. Include `day_of_week` with Monday = 0 and `centered_day`, defined as days since the first analysis date minus the mean day index over the complete grid. Use `log(exposure_customers)` as the Poisson offset.

Fit these maximum-likelihood Poisson generalized linear models with a log link, `maxiter=200`, and `tol=1e-12`:

- `poisson_baseline`: `observed_count ~ C(customer_id) + C(day_of_week)`
- `poisson_trend`: `observed_count ~ C(customer_id) + C(day_of_week) + centered_day + C(customer_id):centered_day`

Select `poisson_trend` exactly when `trend_aic <= baseline_aic - 2.0`; otherwise select `poisson_baseline`. For each coefficient, report its estimate, model-based standard error, z statistic, two-sided normal p value, and 95% Wald interval `estimate ± 1.959963984540054 × standard_error`. For each complete-grid cell, report the selected model's predicted count and the 95% Wald interval on its log mean: calculate the linear predictor and its covariance-based standard error, exponentiate the predictor and both interval endpoints, then divide by `exposure_customers` to obtain the predicted rate and rate bounds.

Write these artifacts:

- `/app/output/model_coefficients.parquet`: columns in this order: `model`, `term`, `estimate`, `standard_error`, `z_value`, `p_value`, `ci_lower`, `ci_upper`. Include every coefficient from both models. Sort by `model`, then `term`.
- `/app/output/model_diagnostics.json`: include each model's log likelihood, AIC, log-likelihood BIC, deviance, Pearson chi-square, overdispersion (`pearson_chi_square / residual_degrees_of_freedom`), parameter count, residual degrees of freedom, and convergence status. Also include the selected model, exact AIC rule, and grid diagnostics.
- `/app/output/predicted_rates.parquet`: columns in this order: `date`, `customer_id`, `exposure_customers`, `observed_count`, `model`, `predicted_count`, `predicted_rate`, `rate_ci_lower`, `rate_ci_upper`. Include one row per grid cell, sorted by `date`, then `customer_id`.
- `/app/output/validation.json`: include status, analysis-unit label, start/end dates, transaction-record count, customer-cohort count, observation-cell count, selected model, AIC selection threshold, input SHA-256, and artifact names.

Serialize JSON with sorted keys, stable indentation, and a final newline. Do not use randomness. The verifier independently rebuilds the grid and both reference fits from its private copy of the transaction data. Required comparisons are exact for schemas, keys, integer/categorical values, convergence flags, and model selection; coefficient estimates and standard errors use absolute tolerance `1e-6`; coefficient z statistics, p values, and confidence bounds use `1e-5`; likelihood, AIC, BIC, deviance, Pearson chi-square, overdispersion, predicted counts, rates, and rate bounds use `1e-5`. All comparisons use zero relative tolerance.

After the agent phase, Harbor runs a verifier-controlled collect hook that fingerprints the four scientific outputs semantically, invokes `/app/src/pipeline/main.py` a second time, and records whether the outputs remain present and unchanged in `/app/output/determinism_report.json`. The separate verifier validates the measurements in that report. You do not need to create that report yourself.
