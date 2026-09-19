import sys
from pathlib import Path

# Ensure pipeline package is importable regardless of working directory
_SRC_DIR = str(Path(__file__).resolve().parent.parent)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import json
import duckdb
from pipeline.config import (
    PREDICTION_CUTOFFS_PATH,
    WAREHOUSE_DB_PATH,
    FEATURES_OUTPUT_PATH,
    VALIDATION_OUTPUT_PATH,
    OUTPUT_DIR
)
from pipeline.ingest import ingest_raw_data
from pipeline.normalize import reconcile_temporal_events
from pipeline.history import point_in_time_customer_join
from pipeline.features import compute_point_in_time_features

def run_pipeline():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WAREHOUSE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(WAREHOUSE_DB_PATH))

    # Stage 1: Load cutoffs
    con.execute("DROP TABLE IF EXISTS staging_cutoffs;")
    con.execute(f"""
        CREATE TABLE staging_cutoffs AS
        SELECT * FROM read_csv_auto('{PREDICTION_CUTOFFS_PATH}')
    """)

    # Stage 2: Ingest raw data
    ingest_raw_data(con)

    # Stage 3: Normalize event stream
    reconcile_temporal_events(con)

    # Stage 4: Point-in-time customer dimensions
    point_in_time_customer_join(con)

    # Stage 5: Compute temporal features
    compute_point_in_time_features(con)

    # Stage 6: Export Parquet and validation summary
    con.execute(f"""
        COPY final_features_table TO '{FEATURES_OUTPUT_PATH}' (FORMAT PARQUET);
    """)

    row_count = con.execute("SELECT COUNT(*) FROM final_features_table").fetchone()[0]
    unique_custs = con.execute("SELECT COUNT(DISTINCT customer_id) FROM final_features_table").fetchone()[0]
    cutoffs_count = con.execute("SELECT COUNT(DISTINCT cutoff_id) FROM final_features_table").fetchone()[0]

    validation = {
        "status": "COMPLETED",
        "row_count": row_count,
        "unique_customers": unique_custs,
        "cutoffs_processed": cutoffs_count,
        "output_file": str(FEATURES_OUTPUT_PATH)
    }

    with open(VALIDATION_OUTPUT_PATH, "w") as f:
        json.dump(validation, f, indent=2)

    print(f"Pipeline executed successfully. Generated {row_count} feature vectors.")
    con.close()

if __name__ == "__main__":
    run_pipeline()

