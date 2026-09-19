# Temporal Feature Store Repair: Customer Churn & Risk Pipeline

## Task overview
In modern machine learning platforms for customer risk, fraud detection, and churn prediction, models are trained on historical snapshots of entity behavior across distinct temporal evaluation cutoffs. A persistent, high-impact failure mode in production feature stores is **temporal leakage and point-in-time state corruption**:
1. Applying dimensional attributes from the current production database snapshot rather than reconstructing the historical Slowly Changing Dimension (SCD Type-2) state as it existed at the prediction cutoff.
2. Conflating transaction event occurrence time (`event_time`) with distributed streaming ingestion time (`ingestion_time`).
3. Leaking future corrections, late arrivals, and out-of-order event revisions into historical feature computation.
4. Non-idempotent table staging resulting in duplicate event inflation upon pipeline reruns or backfills.

This task requires a benchmark agent to act as a senior data/ML engineer to trace, diagnose, and repair an inherited production Python/SQL lakehouse pipeline that runs without runtime errors but yields semantically invalid feature vectors.

## Difficulty explanation

This is a hard, approximately 60-minute expert task. A correct repair must coordinate event-time windows with an ingestion-time knowledge horizon, reconstruct the current event version separately at each cutoff, apply cancellation state, perform an interval SCD Type-2 join, and make persistent staging idempotent. These requirements interact across 2,180 event records, 20 customers, and four historical cutoffs; a local patch to any one stage is insufficient.

## Real-data provenance
The dataset is deterministically derived from the real-world **UCI Online Retail** dataset (`https://github.com/dbdmg/data-science-lab/raw/master/datasets/online_retail.csv`), containing authentic transnational transactions from a UK-based registered non-store online retail platform.
- The raw dataset is deterministically sampled across 20 high-volume international customer cohorts.
- Real invoice records are enriched with production stream metadata: `event_id`, `event_time`, `ingestion_time`, `operation`, `status`, and `version`.
- Synthetic yet realistic production events are deterministically injected:
  - Network duplicate deliveries (identical `event_id` ingested multiple times).
  - Out-of-order and late-arriving records (events occurring weeks prior but ingested later).
  - Multi-version corrections (version 2 updating transaction amounts).
  - Explicit voiding/cancellation events (operation `CANCEL` / status `VOID`).
- Customer dimension state is maintained as an SCD Type-2 dimension (`customer_profiles_scd.jsonl`) with realistic lifecycle tier migrations (`effective_from`, `effective_to`, `is_current`).

## Temporal invariants and invariant reasoning
The task requires four critical temporal invariants:
1. **As-Of Information Horizon**: For cutoff timestamp $T_{\text{cutoff}}$, any record with $\text{ingestion\_time} > T_{\text{cutoff}}$ did not exist in the lakehouse and cannot participate in feature derivation for that cutoff.
2. **Bi-temporal Point-in-Time Event Resolution**: For an event with physical occurrence $\text{event\_time} \le T_{\text{cutoff}}$, its active state at $T_{\text{cutoff}}$ is determined by the highest $(\text{version}, \text{ingestion\_time})$ strictly satisfying $\text{ingestion\_time} \le T_{\text{cutoff}}$. Subsequent corrections ingested after $T_{\text{cutoff}}$ belong strictly to future feature calculations.
3. **Point-in-Time Dimension Alignment**: Customer dimension attributes must satisfy $\text{effective\_from} \le T_{\text{cutoff}} < \text{effective\_to}$.
4. **Idempotent Storage Re-execution**: Staging tables and lakehouse layers must guarantee idempotent upsert/reconciliation without multiplying record counts on backfill execution. The separate verifier confirms the final output's unique grain but cannot directly rerun or inspect agent-controlled pipeline storage without breaking verifier isolation.

## Verification explanation

- Harbor runs the test suite in the configured separate verifier environment built from `tests/Dockerfile`; the agent image does not contain `tests/` or `solution/`.
- The verifier image contains a private, byte-identical copy of the supplied input data so it can independently reconstruct expected results without using the oracle or agent-controlled source files.
- The test suite is implemented in `tests/test_outputs.py` and run via `tests/test.sh`.
- The verifier independently reconstructs every expected feature row from the raw event stream, SCD history, and cutoffs; it does not import or compare against the oracle.
- Tests evaluate:
  - Artifact completeness, parquet schema, data types, and primary key grain `(cutoff_id, customer_id)`.
  - Exact point-in-time dimension state, event reconciliation, cancellation exclusion, and information-horizon gating for all 80 evaluation points.
- Exact rolling-window, lifetime, recency, and utilization values, plus artifact schema and primary-key grain.
- The Oracle is separately run twice during task maintenance to demonstrate deterministic reference artifacts. The verifier does not claim to independently prove repeated pipeline/database execution.
- The verifier writes its standard CTRF report to `/logs/verifier/ctrf.json` and reward to `/logs/verifier/reward.txt`; these are verifier logs, not agent artifacts.

## Solution explanation
`solution/solve.sh` invokes `solution/oracle_engine.py`, which provides a clean, independent implementation of point-in-time bi-temporal evaluation:
- Loads the raw data directly into in-memory temporal data structures.
- For each cutoff, filters the event stream to $\text{ingestion\_time} \le T_{\text{cutoff}}$, resolves the latest event versions, filters out voided transactions, computes exact rolling window aggregations, joins the point-in-time SCD dimension, and writes the Parquet and JSON artifacts.

## Relevant experience

The task represents production work performed by senior data engineers and ML platform engineers responsible for feature stores, event reconciliation, SCD Type-2 dimensions, backfills, and leakage-safe historical model training datasets.
