# Runbook

Concise ops guide for startup, troubleshooting, and recovery.

## Quick setup

1. Copy env defaults: `cp .env.example .env` (edit if local paths differ).
2. Install dependencies: `pip install -r requirements.txt`.
3. API-only baseline mode (no model pickle required):
   `MODEL_VARIANT=baseline uvicorn app.main:app --host 0.0.0.0 --port 8000`
4. Full stack from repo root:
   `docker compose up -d --build`
5. Smoke test:
   `curl -s http://127.0.0.1:8000/health` -> `{"status":"ok"}`

## Startup

1. Start services from repo root:
```bash
docker compose up -d --build
```
2. Verify containers:
```bash
docker compose ps
```
3. Verify API and prediction path:
```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/version
curl -s -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"rows":[{"ret_mean":0.05,"ret_std":0.01,"n":50}]}'
```

## Troubleshooting

### API down / unhealthy
- Check status: `docker compose ps`
- Check API logs: `docker compose logs api --tail=200`
- Restart API: `docker compose restart api`

### High latency or errors
- Metrics:
  - p95 latency: `histogram_quantile(0.95, rate(predict_latency_seconds_bucket[5m]))`
  - error rate: `rate(predict_errors_total[5m]) / rate(predict_requests_total[5m])`
- Check logs: `docker compose logs api --tail=200`
- Send a known-good request to confirm behavior:
```bash
curl -s -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"rows":[{"ret_mean":0.05,"ret_std":0.01,"n":50}]}'
```

### Kafka lag/freshness issues
- Freshness lag: `time() - last_prediction_timestamp_seconds`
- Consumer lag metric: `kafka_consumer_lag_messages`
- Ensure lag config is set on API (`KAFKA_LAG_ENABLED=true`, correct `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_LAG_GROUP_ID`, `KAFKA_LAG_TOPIC`).
- Verify featurizer uses matching group id (`--group_id crypto-featurizer` by default).
- Check broker/API logs:
  - `docker compose logs kafka --tail=200`
  - `docker compose logs api --tail=200`

## Recovery

### Service restart recovery
```bash
docker compose restart api
curl -s http://localhost:8000/health
```

### Model rollback recovery
Switch to baseline model:
```bash
MODEL_VARIANT=baseline docker compose up -d --build api
```
Validate rollback:
```bash
curl -s -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"rows":[{"ret_mean":0.05,"ret_std":0.01,"n":50}]}'
```
Expected: response includes `"model_variant":"baseline"`.
