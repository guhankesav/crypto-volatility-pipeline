# Service Level Objectives

## Scope

These SLOs apply to the FastAPI prediction service exposed at `POST /predict` and the supporting observability stack added for Week 6.

## Targets

- p95 latency: `<= 800 ms` over a 5 minute window. This is aspirational and meant to guide tuning and rollback decisions.
- Error rate: `<= 1%` over a 5 minute window.
- Freshness: at least one successful prediction within the last `60 seconds` while the service is actively receiving traffic.
- Availability: target `99%` successful `POST /predict` responses during expected usage windows.

## PromQL Queries

- p50 latency:
  `histogram_quantile(0.50, rate(predict_latency_seconds_bucket[5m]))`
- p95 latency:
  `histogram_quantile(0.95, rate(predict_latency_seconds_bucket[5m]))`
- Request rate:
  `rate(predict_requests_total[1m])`
- Error rate:
  `rate(predict_errors_total[5m]) / rate(predict_requests_total[5m])`
- Freshness lag:
  `time() - last_prediction_timestamp_seconds`
- **Kafka consumer lag** (unconsumed messages behind the featurizer group, sum over partitions of `ticks.raw`):
  `kafka_consumer_lag_messages`  
  Exposed by the API when `KAFKA_LAG_ENABLED=true` and `KAFKA_LAG_GROUP_ID` matches the featurizer’s `--group_id` (default `crypto-featurizer`). Polling is off in CI / local single-process tests unless you enable it.

## Alert Thresholds

- Latency alert: p95 latency `> 0.8` seconds for 5 minutes.
- Error alert: error rate `> 0.01` for 5 minutes.
- Staleness alert: freshness lag `> 60` seconds for 2 minutes.
- **Kafka consumer lag (optional / workload-dependent):** total lag `> 100 000` messages for 5 minutes (tune to your stream volume).
- Lag poller health: `rate(kafka_lag_scrape_errors_total[5m]) > 0.1` sustained (Kafka unreachable or group metadata issues).

## SLO Violation Definition

An SLO violation occurs when any of the following is true for the alert window:

- `histogram_quantile(0.95, rate(predict_latency_seconds_bucket[5m])) > 0.8`
- `rate(predict_errors_total[5m]) / rate(predict_requests_total[5m]) > 0.01`
- `time() - last_prediction_timestamp_seconds > 60`

Availability is considered out of SLO when repeated `5xx` prediction responses push the error-rate query over the 1% threshold.
