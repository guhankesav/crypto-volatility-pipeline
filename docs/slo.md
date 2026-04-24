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

## Alert Thresholds

- Latency alert: p95 latency `> 0.8` seconds for 5 minutes.
- Error alert: error rate `> 0.01` for 5 minutes.
- Staleness alert: freshness lag `> 60` seconds for 2 minutes.
- Kafka consumer lag: not configured because the API does not currently expose a real lag metric.

## SLO Violation Definition

An SLO violation occurs when any of the following is true for the alert window:

- `histogram_quantile(0.95, rate(predict_latency_seconds_bucket[5m])) > 0.8`
- `rate(predict_errors_total[5m]) / rate(predict_requests_total[5m]) > 0.01`
- `time() - last_prediction_timestamp_seconds > 60`

Availability is considered out of SLO when repeated `5xx` prediction responses push the error-rate query over the 1% threshold.
