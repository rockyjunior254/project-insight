import os
from pathlib import Path

BASE_DIR = Path(os.getenv("APP_DIR", "/app"))
DATA_DIR = BASE_DIR / "data"
WAREHOUSE_DIR = BASE_DIR / "warehouse"
OUTPUT_DIR = BASE_DIR / "output"

RAW_EVENTS_PATH = DATA_DIR / "raw_events.jsonl"
CUSTOMER_PROFILES_PATH = DATA_DIR / "customer_profiles_scd.jsonl"
PREDICTION_CUTOFFS_PATH = DATA_DIR / "prediction_cutoffs.csv"

WAREHOUSE_DB_PATH = WAREHOUSE_DIR / "lakehouse.duckdb"
FEATURES_OUTPUT_PATH = OUTPUT_DIR / "features.parquet"
VALIDATION_OUTPUT_PATH = OUTPUT_DIR / "validation.json"

