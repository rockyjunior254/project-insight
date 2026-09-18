"""
Independent Oracle Calculation for Point-in-Time Temporal Feature Store.
Directly parses raw_events.jsonl, customer_profiles_scd.jsonl, and prediction_cutoffs.csv
implementing rigorous temporal relational semantics without using flawed staging tables.
"""

import csv
import datetime
import json
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

def parse_iso(ts_str: str) -> datetime.datetime:
    return datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")

def solve(data_dir: Path, output_dir: Path):
    events_file = data_dir / "raw_events.jsonl"
    scd_file = data_dir / "customer_profiles_scd.jsonl"
    cutoffs_file = data_dir / "prediction_cutoffs.csv"

    # Read cutoffs
    cutoffs = []
    with open(cutoffs_file, "r") as f:
        reader = csv.DictReader(f)
        for r in reader:
            cutoffs.append({
                "cutoff_id": r["cutoff_id"],
                "cutoff_time": parse_iso(r["cutoff_time"]),
                "cutoff_time_str": r["cutoff_time"]
            })

    # Read customer profiles SCD Type-2
    scd_records = []
    unique_customers = set()
    with open(scd_file, "r") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            scd_records.append({
                "customer_id": int(item["customer_id"]),
                "segment": item["segment"],
                "risk_tier": item["risk_tier"],
                "country": item["country"],
                "credit_limit": float(item["credit_limit"]),
                "effective_from": parse_iso(item["effective_from"]),
                "effective_to": parse_iso(item["effective_to"])
            })
            unique_customers.add(int(item["customer_id"]))

    # Read raw events
    raw_events = []
    with open(events_file, "r") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            raw_events.append({
                "event_id": item["event_id"],
                "customer_id": int(item["customer_id"]),
                "event_time": parse_iso(item["event_time"]),
                "ingestion_time": parse_iso(item["ingestion_time"]),
                "operation": item["operation"],
                "event_type": item["event_type"],
                "amount": float(item["amount"]),
                "status": item["status"],
                "version": int(item["version"])
            })

    results = []

    # For each cutoff, evaluate point-in-time state
    for c in sorted(cutoffs, key=lambda x: x["cutoff_time"]):
        cutoff_id = c["cutoff_id"]
        cutoff_time = c["cutoff_time"]
        cutoff_time_str = c["cutoff_time_str"]

        # 1. Temporal Profile Reconstruction
        # Find profile where effective_from <= cutoff_time < effective_to
        profiles_at_cutoff = {}
        for scd in scd_records:
            if scd["effective_from"] <= cutoff_time < scd["effective_to"]:
                profiles_at_cutoff[scd["customer_id"]] = scd

        # 2. Temporal Event Reconstruction (Point-in-Time as-of cutoff_time)
        # An event record is visible to the pipeline as of cutoff_time if and only if
        # ingestion_time <= cutoff_time.
        # Furthermore, for a given event_id, the effective state at cutoff_time is the
        # latest ingested version (max version, max ingestion_time) among records with ingestion_time <= cutoff_time.
        # Finally, the event belongs to history at event_time! So event_time <= cutoff_time.
        # If the latest state as of cutoff_time has operation == 'CANCEL' or status in ('CANCELLED', 'VOID'),
        # the event is not completed and does not count towards completed spend/count.

        events_by_id = {}
        for ev in raw_events:
            if ev["ingestion_time"] <= cutoff_time:
                eid = ev["event_id"]
                if eid not in events_by_id:
                    events_by_id[eid] = ev
                else:
                    curr = events_by_id[eid]
                    # tie break by version, then ingestion_time
                    if (ev["version"], ev["ingestion_time"]) > (curr["version"], curr["ingestion_time"]):
                        events_by_id[eid] = ev

        # Now group valid completed events by customer_id
        valid_events_by_customer = {cid: [] for cid in unique_customers}
        for eid, ev in events_by_id.items():
            # Event time must be strictly <= cutoff_time to have occurred
            if ev["event_time"] <= cutoff_time:
                # Must be COMPLETED and not CANCELLED/VOID
                if ev["status"] == "COMPLETED" and ev["operation"] not in ("CANCEL", "VOID"):
                    valid_events_by_customer[ev["customer_id"]].append(ev)

        # 3. Compute Features for every customer
        for cid in sorted(unique_customers):
            prof = profiles_at_cutoff[cid]
            c_events = valid_events_by_customer[cid]

            # Rolling windows relative to cutoff_time
            # 30d window: [cutoff_time - 30 days, cutoff_time]
            # 90d window: [cutoff_time - 90 days, cutoff_time]
            t_30d = cutoff_time - datetime.timedelta(days=30)
            t_90d = cutoff_time - datetime.timedelta(days=90)

            w30_count = 0
            w30_spend = 0.0
            w90_count = 0
            w90_spend = 0.0
            lifetime_count = 0
            lifetime_spend = 0.0
            latest_purchase_time = None

            for ev in c_events:
                ev_time = ev["event_time"]
                amt = ev["amount"]

                lifetime_count += 1
                lifetime_spend += amt

                if ev_time >= t_30d:
                    w30_count += 1
                    w30_spend += amt

                if ev_time >= t_90d:
                    w90_count += 1
                    w90_spend += amt

                if latest_purchase_time is None or ev_time > latest_purchase_time:
                    latest_purchase_time = ev_time

            days_since = None
            if latest_purchase_time is not None:
                days_since = round((cutoff_time - latest_purchase_time).total_seconds() / 86400.0, 2)

            limit_util = round(w30_spend / prof["credit_limit"], 4)

            results.append({
                "cutoff_id": cutoff_id,
                "cutoff_time": cutoff_time_str,
                "customer_id": cid,
                "segment": prof["segment"],
                "risk_tier": prof["risk_tier"],
                "country": prof["country"],
                "credit_limit": float(prof["credit_limit"]),
                "window_30d_tx_count": int(w30_count),
                "window_30d_total_spend": round(float(w30_spend), 2),
                "window_90d_tx_count": int(w90_count),
                "window_90d_total_spend": round(float(w90_spend), 2),
                "days_since_last_purchase": days_since,
                "lifetime_completed_tx_count": int(lifetime_count),
                "lifetime_completed_total_spend": round(float(lifetime_spend), 2),
                "limit_utilization_30d": limit_util
            })

    output_dir.mkdir(parents=True, exist_ok=True)
    out_parquet = output_dir / "features.parquet"
    out_val = output_dir / "validation.json"

    # Convert to PyArrow Table
    table = pa.Table.from_pylist(results)
    pq.write_table(table, out_parquet)

    val_data = {
        "status": "COMPLETED",
        "row_count": len(results),
        "unique_customers": len(unique_customers),
        "cutoffs_processed": len(cutoffs),
        "output_file": str(out_parquet)
    }
    with open(out_val, "w") as f:
        json.dump(val_data, f, indent=2)

    print(f"Oracle successfully generated {len(results)} rows to {out_parquet}")

if __name__ == "__main__":
    import sys
    d_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/app/data")
    o_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/app/output")
    solve(d_dir, o_dir)

