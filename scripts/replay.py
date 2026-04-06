import argparse
import glob
import json
import math
import os
from typing import Optional

import pandas as pd


def safe_float(x) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def extract_ticker(payload: dict) -> Optional[dict]:
    if payload.get("channel") != "ticker":
        return None

    events = payload.get("events", [])
    if not events:
        return None

    tickers = events[0].get("tickers", [])
    if not tickers:
        return None

    return tickers[0]


def compute_feature_row(event: dict, prev_midprice: Optional[float]) -> tuple[Optional[dict], Optional[float]]:
    payload = event.get("payload", {})
    ticker = extract_ticker(payload)
    if ticker is None:
        return None, prev_midprice

    price = safe_float(ticker.get("price"))
    best_bid = safe_float(ticker.get("best_bid"))
    best_ask = safe_float(ticker.get("best_ask"))
    bid_qty = safe_float(ticker.get("best_bid_quantity"))
    ask_qty = safe_float(ticker.get("best_ask_quantity"))

    if best_bid is None or best_ask is None:
        return None, prev_midprice

    midprice = (best_bid + best_ask) / 2.0
    spread = best_ask - best_bid

    log_return = None
    if prev_midprice is not None and prev_midprice > 0 and midprice > 0:
        log_return = math.log(midprice / prev_midprice)

    feature_row = {
        "ingest_time": event.get("ingest_time"),
        "exchange_time": payload.get("timestamp"),
        "product_id": event.get("product_id"),
        "price": price,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "best_bid_quantity": bid_qty,
        "best_ask_quantity": ask_qty,
        "midprice": midprice,
        "spread": spread,
        "log_return": log_return,
    }

    return feature_row, midprice


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=str, default="data/raw/*.ndjson")
    parser.add_argument("--out", type=str, default="data/processed/features_replay.parquet")
    args = parser.parse_args()

    raw_files = sorted(glob.glob(args.raw))
    if not raw_files:
        print(f"No raw files matched: {args.raw}")
        return

    rows = []
    prev_midprice = None

    for path in raw_files:
        print(f"Reading raw file: {path}")
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                event = json.loads(line)
                feature_row, prev_midprice = compute_feature_row(event, prev_midprice)
                if feature_row is not None:
                    rows.append(feature_row)

    if not rows:
        print("No replay feature rows generated.")
        return

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_parquet(args.out, index=False)

    print(f"Saved {len(df)} replay feature rows to {args.out}")
    print("Replay complete.")


if __name__ == "__main__":
    main()