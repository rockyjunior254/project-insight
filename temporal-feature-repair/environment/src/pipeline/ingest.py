import json
import duckdb
from pipeline.config import RAW_EVENTS_PATH, CUSTOMER_PROFILES_PATH, WAREHOUSE_DB_PATH

def init_warehouse(con: duckdb.DuckDBPyConnection):
    con.execute("""
        CREATE TABLE IF NOT EXISTS staging_raw_events (
            event_id VARCHAR,
            customer_id BIGINT,
            event_time TIMESTAMP,
            ingestion_time TIMESTAMP,
            operation VARCHAR,
            event_type VARCHAR,
            amount DOUBLE,
            status VARCHAR,
            version INTEGER
        );
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS staging_customer_profiles (
            customer_id BIGINT,
            segment VARCHAR,
            risk_tier VARCHAR,
            country VARCHAR,
            credit_limit DOUBLE,
            effective_from TIMESTAMP,
            effective_to TIMESTAMP,
            is_current BOOLEAN
        );
    """)

def ingest_raw_data(con: duckdb.DuckDBPyConnection):
    init_warehouse(con)
    # Flawed ingestion: appends raw lines into staging without transactional deduplication or idempotent replace
    con.execute(f"""
        INSERT INTO staging_raw_events
        SELECT
            event_id,
            customer_id,
            CAST(event_time AS TIMESTAMP) AS event_time,
            CAST(ingestion_time AS TIMESTAMP) AS ingestion_time,
            operation,
            event_type,
            amount,
            status,
            version
        FROM read_json_auto('{RAW_EVENTS_PATH}')
    """)

    con.execute(f"""
        INSERT INTO staging_customer_profiles
        SELECT
            customer_id,
            segment,
            risk_tier,
            country,
            credit_limit,
            CAST(effective_from AS TIMESTAMP) AS effective_from,
            CAST(effective_to AS TIMESTAMP) AS effective_to,
            is_current
        FROM read_json_auto('{CUSTOMER_PROFILES_PATH}')
    """)

