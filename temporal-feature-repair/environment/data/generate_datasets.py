"""
Deterministic generation of raw production event stream and customer dimensions
derived directly from the real UCI Online Retail dataset.
"""

import csv
import datetime
import hashlib
import io
import json
import os
import random
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent

UCI_URL = "https://github.com/dbdmg/data-science-lab/raw/master/datasets/online_retail.csv"

# 20 diverse, highly-active customers spanning UK and international segments
TARGET_CUSTOMERS = [
    17841, 14911, 14096, 12748, 14606, 15311, 14646, 13089, 13263, 14298,
    15039, 14156, 17920, 18102, 17450, 12415, 14159, 16029, 17511, 16684
]

SEGMENTS = ["ENTERPRISE", "MIDMARKET", "GROWTH", "SMB", "RETAIL"]
COUNTRIES = ["United Kingdom", "Germany", "France", "EIRE", "Netherlands", "Spain"]

def deterministic_hash(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()[:16]

def main():
    print("Downloading and processing UCI Online Retail dataset...")
    req = urllib.request.Request(UCI_URL, headers={"User-Agent": "Mozilla/5.0"})
    
    # Store customer raw transactions
    customer_txns = {c: [] for c in TARGET_CUSTOMERS}
    
    with urllib.request.urlopen(req) as resp:
        reader = csv.DictReader(io.TextIOWrapper(resp, encoding="utf-8", errors="replace"))
        for row in reader:
            cid_str = row.get("CustomerID", "").strip()
            if not cid_str:
                continue
            try:
                cid = int(float(cid_str))
            except ValueError:
                continue
            if cid in customer_txns:
                inv_no = row.get("InvoiceNo", "").strip()
                stock_code = row.get("StockCode", "").strip()
                desc = row.get("Description", "").strip()
                qty_str = row.get("Quantity", "0").strip()
                dt_str = row.get("InvoiceDate", "").strip()
                price_str = row.get("UnitPrice", "0").strip()
                country = row.get("Country", "").strip()
                try:
                    qty = int(qty_str)
                    price = float(price_str)
                    dt = datetime.datetime.strptime(dt_str, "%m/%d/%Y %H:%M")
                except Exception:
                    continue
                amount = round(qty * price, 2)
                customer_txns[cid].append({
                    "invoice_no": inv_no,
                    "stock_code": stock_code,
                    "description": desc,
                    "quantity": qty,
                    "event_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "unit_price": price,
                    "amount": amount,
                    "country": country or "United Kingdom"
                })

    for cid in TARGET_CUSTOMERS:
        print(f"Customer {cid}: {len(customer_txns[cid])} transactions")

    rng = random.Random(42)  # Strictly deterministic seed
    raw_events = []
    
    for cid in TARGET_CUSTOMERS:
        txns = sorted(customer_txns[cid], key=lambda x: x["event_time"])
        step = max(1, len(txns) // 80)
        sampled = txns[::step][:80]

        for i, t in enumerate(sampled):
            base_dt = datetime.datetime.strptime(t["event_time"], "%Y-%m-%d %H:%M:%S")
            key_str = f"{cid}-{i}-{t['invoice_no']}-{t['stock_code']}"
            event_id = f"EVT-{cid}-{deterministic_hash(key_str)}"
            
            # Normal ingestion is within 5-15 minutes of event_time
            ingestion_dt = base_dt + datetime.timedelta(minutes=rng.randint(5, 15))
            op = "INSERT"
            status = "COMPLETED" if t["amount"] >= 0 else "CANCELLED"
            amount = abs(t["amount"])

            # Case A: Normal event
            raw_events.append({
                "event_id": event_id,
                "customer_id": cid,
                "event_time": base_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "ingestion_time": ingestion_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "operation": op,
                "event_type": "PURCHASE" if status == "COMPLETED" else "REFUND",
                "amount": amount,
                "status": status,
                "version": 1
            })

            # Case B: Deterministic duplicate delivery
            if i % 7 == 3:
                dup_dt = ingestion_dt + datetime.timedelta(minutes=rng.randint(30, 180))
                raw_events.append({
                    "event_id": event_id,
                    "customer_id": cid,
                    "event_time": base_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "ingestion_time": dup_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "operation": op,
                    "event_type": "PURCHASE" if status == "COMPLETED" else "REFUND",
                    "amount": amount,
                    "status": status,
                    "version": 1
                })

            # Case C: Deterministic Correction / Replacement
            if i % 11 == 4:
                corr_dt = base_dt + datetime.timedelta(days=rng.randint(2, 5))
                corr_amount = round(amount * 0.8, 2)
                raw_events.append({
                    "event_id": event_id,
                    "customer_id": cid,
                    "event_time": base_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "ingestion_time": corr_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "operation": "UPDATE",
                    "event_type": "PURCHASE",
                    "amount": corr_amount,
                    "status": "COMPLETED",
                    "version": 2
                })

            # Case D: Deterministic Late-Arriving Event
            if i % 13 == 6:
                late_key = f"late-{cid}-{i}"
                late_event_id = f"EVT-LATE-{cid}-{deterministic_hash(late_key)}"
                late_event_time = base_dt - datetime.timedelta(days=rng.randint(10, 20))
                raw_events.append({
                    "event_id": late_event_id,
                    "customer_id": cid,
                    "event_time": late_event_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "ingestion_time": ingestion_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "operation": "INSERT",
                    "event_type": "PURCHASE",
                    "amount": round(amount * 1.5 + 10.0, 2),
                    "status": "COMPLETED",
                    "version": 1
                })

            # Case E: Explicit Cancellation / Deletion event
            if i % 17 == 8:
                cancel_dt = base_dt + datetime.timedelta(days=1, hours=2)
                raw_events.append({
                    "event_id": event_id,
                    "customer_id": cid,
                    "event_time": base_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "ingestion_time": cancel_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "operation": "CANCEL",
                    "event_type": "PURCHASE",
                    "amount": 0.0,
                    "status": "VOID",
                    "version": 3
                })

    raw_events.sort(key=lambda x: (x["ingestion_time"], x["event_id"]))

    out_events_file = DATA_DIR / "raw_events.jsonl"
    with open(out_events_file, "w") as f:
        for ev in raw_events:
            f.write(json.dumps(ev) + "\n")
    print(f"Wrote {len(raw_events)} events to {out_events_file}")

    # Build SCD Type-2 customer profiles: customer_profiles_scd.jsonl
    scd_records = []
    for cid in TARGET_CUSTOMERS:
        t0 = "2010-01-01 00:00:00"
        t1 = "2011-04-15 12:00:00"
        t2 = "2011-09-01 00:00:00"

        c_hash = int(deterministic_hash(str(cid))[:8], 16)
        seg0 = SEGMENTS[c_hash % len(SEGMENTS)]
        seg1 = SEGMENTS[(c_hash + 1) % len(SEGMENTS)]
        country = COUNTRIES[c_hash % len(COUNTRIES)]
        limit0 = 5000 + (c_hash % 5) * 2500
        limit1 = limit0 + 5000
        limit2 = limit1 + 2500

        scd_records.append({
            "customer_id": cid,
            "segment": seg0,
            "risk_tier": "STANDARD",
            "country": country,
            "credit_limit": limit0,
            "effective_from": t0,
            "effective_to": t1,
            "is_current": False
        })
        scd_records.append({
            "customer_id": cid,
            "segment": seg1,
            "risk_tier": "PREFERRED" if limit1 >= 10000 else "STANDARD",
            "country": country,
            "credit_limit": limit1,
            "effective_from": t1,
            "effective_to": t2,
            "is_current": False
        })
        scd_records.append({
            "customer_id": cid,
            "segment": seg1,
            "risk_tier": "VIP" if limit2 >= 15000 else "PREFERRED",
            "country": country,
            "credit_limit": limit2,
            "effective_from": t2,
            "effective_to": "9999-12-31 23:59:59",
            "is_current": True
        })

    out_scd_file = DATA_DIR / "customer_profiles_scd.jsonl"
    with open(out_scd_file, "w") as f:
        for rec in scd_records:
            f.write(json.dumps(rec) + "\n")
    print(f"Wrote {len(scd_records)} customer profile SCD records to {out_scd_file}")

    cutoffs = [
        {"cutoff_id": "CUTOFF_2011_03_31", "cutoff_time": "2011-03-31 23:59:59"},
        {"cutoff_id": "CUTOFF_2011_06_30", "cutoff_time": "2011-06-30 23:59:59"},
        {"cutoff_id": "CUTOFF_2011_10_31", "cutoff_time": "2011-10-31 23:59:59"},
        {"cutoff_id": "CUTOFF_2011_12_05", "cutoff_time": "2011-12-05 23:59:59"}
    ]
    out_cutoff_file = DATA_DIR / "prediction_cutoffs.csv"
    with open(out_cutoff_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["cutoff_id", "cutoff_time"])
        writer.writeheader()
        for row in cutoffs:
            writer.writerow(row)
    print(f"Wrote {len(cutoffs)} cutoffs to {out_cutoff_file}")

    print("Data derivation complete successfully.")

if __name__ == "__main__":
    main()
