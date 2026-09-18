import duckdb

def compute_point_in_time_features(con: duckdb.DuckDBPyConnection):
    """
    Computes rolling window aggregations and customer metrics relative to each cutoff.
    """
    con.execute("DROP TABLE IF EXISTS final_features_table;")
    # Flawed:
    # 1. Joins silver_events where e.effective_timestamp <= c.cutoff_time, but effective_timestamp
    #    in silver_events was set to ingestion_time (corrupted late arrival handling).
    # 2. Does NOT filter out future corrections that were ingested AFTER cutoff_time (future leakage!).
    # 3. Includes CANCELLED or VOID records in sum(amount).
    # 4. Window intervals use string arithmetic or inaccurate date boundaries.
    con.execute("""
        CREATE TABLE final_features_table AS
        WITH customer_cutoff_events AS (
            SELECT
                b.cutoff_id,
                b.cutoff_time,
                b.customer_id,
                b.segment,
                b.risk_tier,
                b.country,
                b.credit_limit,
                e.event_id,
                e.effective_timestamp,
                e.amount,
                e.status,
                epoch(b.cutoff_time) - epoch(e.effective_timestamp) AS age_seconds
            FROM gold_customer_cutoffs b
            LEFT JOIN silver_events e
                ON b.customer_id = e.customer_id
                AND e.effective_timestamp <= b.cutoff_time
        )
        SELECT
            cutoff_id,
            strftime(cutoff_time, '%Y-%m-%d %H:%M:%S') AS cutoff_time,
            customer_id,
            segment,
            risk_tier,
            country,
            credit_limit,
            COUNT(CASE WHEN age_seconds <= 30*86400 AND age_seconds >= 0 AND event_id IS NOT NULL THEN 1 END) AS window_30d_tx_count,
            COALESCE(ROUND(SUM(CASE WHEN age_seconds <= 30*86400 AND age_seconds >= 0 THEN amount ELSE 0.0 END), 2), 0.0) AS window_30d_total_spend,
            COUNT(CASE WHEN age_seconds <= 90*86400 AND age_seconds >= 0 AND event_id IS NOT NULL THEN 1 END) AS window_90d_tx_count,
            COALESCE(ROUND(SUM(CASE WHEN age_seconds <= 90*86400 AND age_seconds >= 0 THEN amount ELSE 0.0 END), 2), 0.0) AS window_90d_total_spend,
            ROUND(MIN(CASE WHEN event_id IS NOT NULL THEN age_seconds / 86400.0 END), 2) AS days_since_last_purchase,
            COUNT(CASE WHEN event_id IS NOT NULL THEN 1 END) AS lifetime_completed_tx_count,
            COALESCE(ROUND(SUM(amount), 2), 0.0) AS lifetime_completed_total_spend,
            ROUND(COALESCE(SUM(CASE WHEN age_seconds <= 30*86400 AND age_seconds >= 0 THEN amount ELSE 0.0 END), 0.0) / credit_limit, 4) AS limit_utilization_30d
        FROM customer_cutoff_events
        GROUP BY cutoff_id, cutoff_time, customer_id, segment, risk_tier, country, credit_limit
        ORDER BY cutoff_id, customer_id
    """)

