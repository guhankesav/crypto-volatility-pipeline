import argparse
import json
import time
from kafka import KafkaProducer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--topic", default="ticks.raw")
    parser.add_argument("--bootstrap_servers", default="localhost:29092")
    parser.add_argument("--sleep_ms", type=int, default=100)
    args = parser.parse_args()

    producer = KafkaProducer(
        bootstrap_servers=args.bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8")
    )

    count = 0
    with open(args.input, "r", encoding="utf-8") as f:
        for line in f:
            event = json.loads(line)
            producer.send(args.topic, event)
            count += 1
            if count % 50 == 0:
                producer.flush()
            time.sleep(args.sleep_ms / 1000.0)

    producer.flush()
    print(f"Published {count} events to {args.topic}")


if __name__ == "__main__":
    main()