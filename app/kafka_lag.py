"""
Poll Kafka (admin + log-end) for consumer-group lag; update Prometheus gauges in a background thread.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

KAFKA_LAG_ENABLED = os.getenv("KAFKA_LAG_ENABLED", "false").lower() in ("1", "true", "yes")
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_LAG_GROUP = os.getenv("KAFKA_LAG_GROUP_ID", "crypto-featurizer")
KAFKA_LAG_TOPIC = os.getenv("KAFKA_LAG_TOPIC", "ticks.raw")
KAFKA_LAG_INTERVAL = float(os.getenv("KAFKA_LAG_SCRAPE_INTERVAL_SECONDS", "15"))


def _compute_lag() -> float | None:
    from kafka import KafkaAdminClient, KafkaConsumer

    admin = KafkaAdminClient(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        request_timeout_ms=20000,
    )
    try:
        committed = admin.list_consumer_group_offsets(KAFKA_LAG_GROUP, partitions=None)
    except Exception as exc:  # noqa: BLE001 - broker / auth errors
        log.debug("list_consumer_group_offsets: %s", exc)
        return None
    finally:
        admin.close()

    if not committed:
        return 0.0

    tps = [tp for tp in committed if tp.topic == KAFKA_LAG_TOPIC]
    if not tps:
        return 0.0

    consumer = KafkaConsumer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        consumer_timeout_ms=20000,
    )
    try:
        try:
            ends = consumer.end_offsets(tps)
        except Exception as exc:  # noqa: BLE001
            log.debug("end_offsets: %s", exc)
            return None
    finally:
        consumer.close()

    total = 0.0
    for tp in tps:
        meta = committed[tp]
        com = int(getattr(meta, "offset", 0) or 0)
        if com < 0:
            com = 0
        end = ends.get(tp)
        if end is None:
            continue
        total += max(0.0, float(end) - float(com))
    return total


def _loop(lag_gauge: Any, err_counter: Any) -> None:
    while True:
        value = _compute_lag()
        if value is None:
            err_counter.inc()
        else:
            lag_gauge.set(value)
        time.sleep(KAFKA_LAG_INTERVAL)


def start_polling(
    lag_gauge: Any,
    err_counter: Any,
) -> None:
    if not KAFKA_LAG_ENABLED:
        log.info("KAFKA_LAG_ENABLED is false: skipping consumer-lag poller (CI / no Kafka).")
        return
    t = threading.Thread(
        target=_loop,
        args=(lag_gauge, err_counter),
        name="kafka-lag",
        daemon=True,
    )
    t.start()
    log.info(
        "Kafka consumer lag poller started (group=%r topic=%r interval=%ss).",
        KAFKA_LAG_GROUP,
        KAFKA_LAG_TOPIC,
        KAFKA_LAG_INTERVAL,
    )
