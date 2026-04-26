import argparse
import json
import os
import signal
import time
from datetime import datetime, timezone

import websocket
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

WS_URL = "wss://advanced-trade-ws.coinbase.com"

_shutdown_requested = False


def _handle_signal(signum, frame):
    global _shutdown_requested
    print(f"Signal {signum} received — shutting down ingestor...")
    _shutdown_requested = True


def make_producer(bootstrap_servers: str) -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )


def get_producer_with_retry(
    bootstrap_servers: str,
    max_retries: int = 15,
    retry_delay: int = 3,
) -> KafkaProducer:
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            producer = make_producer(bootstrap_servers)
            print(
                f"Connected to Kafka at {bootstrap_servers} "
                f"(attempt {attempt}/{max_retries})"
            )
            return producer
        except NoBrokersAvailable as e:
            last_error = e
            print(
                f"Kafka not ready yet at {bootstrap_servers} "
                f"(attempt {attempt}/{max_retries}). Retrying in {retry_delay}s..."
            )
            time.sleep(retry_delay)

    raise RuntimeError(
        f"Could not connect to Kafka at {bootstrap_servers} after "
        f"{max_retries} attempts"
    ) from last_error


def build_subscribe_message(product_id: str) -> dict:
    return {
        "type": "subscribe",
        "channel": "ticker",
        "product_ids": [product_id],
    }


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", type=str, default="BTC-USD")
    parser.add_argument("--minutes", type=int, default=15)
    parser.add_argument("--bootstrap_servers", type=str, default="kafka:9092")
    args = parser.parse_args()

    producer = get_producer_with_retry(args.bootstrap_servers)
    end_time = time.time() + args.minutes * 60

    os.makedirs("data/raw", exist_ok=True)
    out_path = os.path.join("data/raw", f"{args.pair.replace('-', '_')}.ndjson")

    msg_count = 0

    while time.time() < end_time and not _shutdown_requested:
        ws = None
        try:
            ws = websocket.create_connection(WS_URL, timeout=30)

            # Heartbeat handling:
            # If no messages are received within 10 seconds, a timeout triggers
            # reconnection and re-subscription.
            ws.settimeout(10)

            subscribe_msg = build_subscribe_message(args.pair)
            ws.send(json.dumps(subscribe_msg))
            print(f"Subscribed to {args.pair}")

            while time.time() < end_time and not _shutdown_requested:
                try:
                    raw_msg = ws.recv()
                    if not raw_msg:
                        continue
                except websocket.WebSocketTimeoutException:
                    print("No data received for 10 seconds. Reconnecting...")
                    raise Exception("Heartbeat timeout")

                parsed = json.loads(raw_msg)
                event = {
                    "ingest_time": datetime.now(timezone.utc).isoformat(),
                    "product_id": args.pair,
                    "payload": parsed,
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
