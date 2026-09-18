import duckdb

def reconcile_temporal_events(con: duckdb.DuckDBPyConnection):
    """
    Normalizes and deduplicates staging event streams into a cleaned event log.
    """
    con.execute("DROP TABLE IF EXISTS silver_events;")
    # Initial flawed logic:
    # 1. Takes the maximum ingestion_time row per event_id, BUT groups only by event_id without
    #    point-in-time state resolution, and ignores CANCEL/VOID operation semantics.
    # 2. Replaces event_time with ingestion_time in downstream calculations!
    con.execute("""
        CREATE TABLE silver_events AS
        SELECT
            event_id,
            customer_id,
            ingestion_time AS effective_timestamp, -- Flawed: Uses ingestion_time instead of event_time
            event_time,
            ingestion_time,
            operation,
            event_type,
            amount,
            status,
            version
        FROM (
            SELECT *,
                ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY version DESC, ingestion_time DESC) as rn
            FROM staging_raw_events
        )
        WHERE rn = 1
    """)

