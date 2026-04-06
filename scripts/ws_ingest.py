import argparse
import json
import os
import time
from datetime import datetime, timezone

import websocket
from kafka import KafkaProducer

WS_URL = "wss://advanced-trade-ws.coinbase.com"


def make_producer(bootstrap_servers: str):
    return KafkaProducer(
        bootstrap_servers=bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8")
    )


def build_subscribe_message(product_id: str):
    return {
        "type": "subscribe",
        "channel": "ticker",
        "product_ids": [product_id]
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", type=str, default="BTC-USD")
    parser.add_argument("--minutes", type=int, default=15)
    parser.add_argument("--bootstrap_servers", type=str, default="localhost:9092")
    args = parser.parse_args()

    producer = make_producer(args.bootstrap_servers)
    end_time = time.time() + args.minutes * 60

    os.makedirs("data/raw", exist_ok=True)
    out_path = os.path.join("data/raw", f"{args.pair.replace('-', '_')}.ndjson")

    msg_count = 0

    while time.time() < end_time:
        ws = None
        try:
            ws = websocket.create_connection(WS_URL, timeout=30)
            subscribe_msg = build_subscribe_message(args.pair)
            ws.send(json.dumps(subscribe_msg))
            print(f"Subscribed to {args.pair}")

            while time.time() < end_time:
                raw_msg = ws.recv()
                if not raw_msg:
                    continue

                parsed = json.loads(raw_msg)
                event = {
                    "ingest_time": datetime.now(timezone.utc).isoformat(),
                    "product_id": args.pair,
                    "payload": parsed
                }

                producer.send("ticks.raw", event)

                with open(out_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event) + "\n")

                msg_count += 1
                if msg_count % 10 == 0:
                    print(f"Ingested {msg_count} messages...")

                if msg_count % 50 == 0:
                    producer.flush()

        except Exception as e:
            print(f"Connection error: {e}")
            print("Reconnecting in 5 seconds...")
            time.sleep(5)
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    producer.flush()
    print(f"Ingestion finished. Total messages: {msg_count}")


if __name__ == "__main__":
    main()