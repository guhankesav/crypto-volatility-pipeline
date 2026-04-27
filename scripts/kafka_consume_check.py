import argparse
import json
from kafka import KafkaConsumer

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", type=str, default="ticks.raw")
    parser.add_argument("--bootstrap_servers", type=str, default="localhost:9092")
    parser.add_argument("--min", type=int, default=5)
    args = parser.parse_args()

    print(f"Connecting to Kafka at {args.bootstrap_servers}")
    print(f"Listening on topic: {args.topic}")

    consumer = KafkaConsumer(
        args.topic,
        bootstrap_servers=args.bootstrap_servers,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        consumer_timeout_ms=10000,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )

    count = 0
    for msg in consumer:
        print(msg.value)
        count += 1
        if count >= args.min:
            print(f"Received at least {args.min} messages. Kafka consumer check passed.")
            return

    print("No messages received before timeout.")

if __name__ == "__main__":
    main()
