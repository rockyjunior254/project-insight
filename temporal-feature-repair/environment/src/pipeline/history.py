import duckdb

def point_in_time_customer_join(con: duckdb.DuckDBPyConnection):
    """
    Joins customer dimension profiles to cutoffs.
    """
    con.execute("DROP TABLE IF EXISTS gold_customer_cutoffs;")
    # Flawed: Joins only the currently active profile (is_current = True) to all cutoffs,
    # completely ignoring effective_from and effective_to historical intervals!
    con.execute("""
        CREATE TABLE gold_customer_cutoffs AS
        SELECT
            c.cutoff_id,
            CAST(c.cutoff_time AS TIMESTAMP) AS cutoff_time,
            p.customer_id,
            p.segment,
            p.risk_tier,
            p.country,
            p.credit_limit
        FROM staging_cutoffs c
        CROSS JOIN staging_customer_profiles p
        WHERE p.is_current = True
    """)

