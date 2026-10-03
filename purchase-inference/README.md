# Purchase Intensity Inference

Task: **Inference and Calibration of Purchase-Intensity Dynamics from Retail Transactions**  
Package: `afterquery/purchase-inference`  
Taxonomy: Science → mathematical-sciences → statistics → Statistics & Machine Learning → time-series inference and uncertainty quantification

This task asks the agent to build a reproducible customer-day count analysis from the supplied retail records. It compares a customer and weekday Poisson baseline with a richer model that allows customer-specific linear time trends, quantifies coefficient and prediction uncertainty, reports likelihood and residual diagnostics, and applies a fixed AIC selection threshold.

## Data scope

The release contains 2,032 row-level records for 20 curated, high-activity customers across 385 calendar days. One JSONL row is the counted record; identical time-and-amount values can occur on distinct records. The observation unit is a calendar day for one customer, with one customer-day of exposure. These customers are a selected case study, not a probability sample, so the estimates describe only this release. Geographic or segment effects are not estimated: labels in the earlier generated profile data were deterministic assignments rather than observed customer attributes.

## Difficulty explanation

The work combines complete-grid construction, exposure-aware Poisson estimation, two nested model fits, model-based uncertainty, likelihood and residual diagnostics, a numerical selection rule, and reproducible artifact production. Correctness depends on preserving the same observation unit and model specification across coefficients, confidence intervals, predicted rates, diagnostics, and validation metadata.

## Solution explanation

A valid pipeline derives the calendar span and customer set from the input records, fills every customer-day cell, calculates counts and centered time, fits both specified Poisson GLMs, then applies the `2.0` AIC improvement rule. It reports Wald intervals for coefficients and log-mean prediction intervals for each cell, and writes the four scientific artifacts with the required schemas and stable sort order.

## Verification explanation

The separate verifier reads its own byte-identical copy of the transaction release and independently reconstructs the grid and fits using an explicit design matrix. It checks schemas, complete keys, all coefficient and prediction values, diagnostics, validation metadata, and the exact model-selection rule with fixed absolute tolerances. A Harbor collect hook runs after the agent phase, snapshots semantic fingerprints for the four scientific outputs, invokes `/app/src/pipeline/main.py` again, and records the run status and before/after fingerprints in `determinism_report.json`. The verifier validates those measurements; it does not import the Oracle implementation or the agent pipeline.

## Relevant experience

The task is suited to someone comfortable with generalized linear models, Poisson likelihoods, categorical design matrices, confidence intervals, information criteria, residual diagnostics, and reproducible Python data analysis.

## Running local validation

From this directory, run the actual Harbor trials:

```bash
harbor run -p . -a oracle -e docker
harbor run -p . -a nop -e docker
```

The Oracle is a separate reference procedure. NOP performs no agent work; it should receive reward `0` because the required outputs are absent.
