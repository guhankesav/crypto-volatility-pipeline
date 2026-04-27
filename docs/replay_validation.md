# Replay-to-Serving Validation Path

Single end-to-end flow to validate the intended path:

`raw ndjson -> Kafka (ticks.raw) -> featurizer -> Kafka (ticks.features) + parquet -> API /predict`

## 1) Start stack

```bash
docker compose up -d --build
```

## 2) Publish replay events to Kafka raw topic

```bash
python scripts/replay_to_kafka.py \
  --input data/raw/BTC_USD.ndjson \
  --topic ticks.raw \
  --bootstrap_servers localhost:29092 \
  --sleep_ms 5
```

## 3) Run featurizer against Kafka stream

```bash
python features/featurizer.py \
  --topic_in ticks.raw \
  --topic_out ticks.features \
  --bootstrap_servers localhost:29092 \
  --group_id crypto-featurizer \
  --max_messages 100 \
  --out_path data/processed/features_from_kafka.parquet
```

Expected: `data/processed/features_from_kafka.parquet` is created and `ticks.features` receives feature rows.

## 4) Call API predict endpoint (serving contract)

```bash
curl -s -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"rows":[{"ret_mean":0.05,"ret_std":0.01,"n":50}]}' 
```

Expected response shape:

```json
{
  "scores": [0.74],
  "model_variant": "ml",
  "version": "v1.2",
  "ts": "2026-04-26T18:00:00Z"
}
```

## 5) Optional checks

- API metrics: `curl -s http://localhost:8000/metrics`
- Kafka lag metric: `kafka_consumer_lag_messages` (requires `KAFKA_LAG_ENABLED=true`)
- Health: `curl -s http://localhost:8000/health`
