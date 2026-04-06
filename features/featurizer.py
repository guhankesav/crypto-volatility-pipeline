import argparse
import json
import math
import os
from typing import Optional

import pandas as pd
from kafka import KafkaConsumer, KafkaProducer


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic_in", type=str, default="ticks.raw")
    parser.add_argument("--topic_out", type=str, default="ticks.features")
    parser.add_argument("--bootstrap_servers", type=str, default="localhost:9092")
    parser.add_argument("--max_messages", type=int, default=100)
    args = parser.parse_args()

    consumer = KafkaConsumer(
        args.topic_in,
        bootstrap_servers=args.bootstrap_servers,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        consumer_timeout_ms=15000,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )

    producer = KafkaProducer(
        bootstrap_servers=args.bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8")
    )

    rows = []
    prev_midprice = None
    processed = 0

    print(f"Reading from {args.topic_in} and writing to {args.topic_out}")

    for msg in consumer:
        event = msg.value
        payload = event.get("payload", {})
        ticker = extract_ticker(payload)

        if ticker is None:
            continue

        price = safe_float(ticker.get("price"))
        best_bid = safe_float(ticker.get("best_bid"))
        best_ask = safe_float(ticker.get("best_ask"))
        bid_qty = safe_float(ticker.get("best_bid_quantity"))
        ask_qty = safe_float(ticker.get("best_ask_quantity"))

        if best_bid is None or best_ask is None:
            continue

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

        producer.send(args.topic_out, feature_row)
        rows.append(feature_row)

        prev_midprice = midprice
        processed += 1

        if processed % 10 == 0:
            print(f"Processed {processed} feature rows")

        if processed >= args.max_messages:
            break

    producer.flush()

    if rows:
        os.makedirs("data/processed", exist_ok=True)
        df = pd.DataFrame(rows)
        out_path = "data/processed/features.parquet"
        df.to_parquet(out_path, index=False)
        print(f"Saved {len(df)} rows to {out_path}")
    else:
        print("No feature rows generated.")

    print("Featurization complete.")


if __name__ == "__main__":
    main()