# Week 6 Runbook

## Startup

Run the full stack from the repository root:

```bash
docker compose up -d --build
```

If you prefer the original compose path, this also works:

```bash
docker compose -f docker/compose.yaml up -d --build
```

## Health Checks

Run these checks after startup:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/version
curl http://localhost:8000/metrics
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"rows":[{"ret_mean":0.05,"ret_std":0.01,"n":50}]}'
```

Expected ports:

- API: `http://localhost:8000`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`
- MLflow: `http://localhost:5001`

## Prometheus And Grafana

- Prometheus scrapes `crypto-api:8000/metrics`.
- Alert rules are loaded from `docker/prometheus_alerts.yml`.
- Grafana is provisioned with the Prometheus datasource automatically.
- The Week 6 dashboard is stored at `docker/grafana/dashboards/crypto_week6_dashboard.json`.
- Default Grafana credentials in compose are `admin` / `admin`.

## Dashboard Import And Viewing

- Open Grafana and look in the `Week 6` folder for `Crypto Volatility Week 6`.
- If provisioning does not load automatically, import `docker/grafana/dashboards/crypto_week6_dashboard.json` manually from the Grafana UI.
- Use the dashboard panels to watch latency, request rate, error rate, and freshness.

## Manual Screenshot Capture

- Open the Grafana dashboard in a browser.
- Set the time range you want to capture.
- Use your OS screenshot tool to capture the full dashboard or the relevant panels.
- Save the screenshot alongside your assignment notes if your instructor wants visual proof.

## Troubleshooting

### High latency

- Check `histogram_quantile(0.95, rate(predict_latency_seconds_bucket[5m]))` in Grafana or Prometheus.
- Confirm the API container is healthy with `docker compose ps`.
- Inspect API logs with `docker compose logs crypto-api`.
- If latency regressed after a model change, switch to `MODEL_VARIANT=baseline` and redeploy.

### High error rate

- Query `rate(predict_errors_total[5m]) / rate(predict_requests_total[5m])`.
- Check the API logs for stack traces.
- Validate the request body still matches the required contract.
- Confirm the model artifact path exists inside the API container.

### Stale data

- Query `time() - last_prediction_timestamp_seconds`.
- Trigger a known-good prediction request manually.
- If freshness stays stale, inspect the API logs and confirm requests are reaching the service.

### Kafka issues

- Confirm Kafka is running with `docker compose ps kafka`.
- Inspect Kafka container logs with `docker compose logs kafka`.
- The Week 6 API monitoring does not expose consumer lag because no real lag metric is currently emitted.
- If replay or live ingestion is failing, validate broker connectivity on `localhost:29092`.

## Rollback

To roll back to the deterministic baseline model path:

```bash
MODEL_VARIANT=baseline docker compose up -d --build
```

Verify rollback:

```bash
curl http://localhost:8000/version
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"rows":[{"ret_mean":0.05,"ret_std":0.01,"n":50}]}'
```

The prediction response should include `"model_variant":"baseline"`. The `/version` endpoint remains limited to `model` and `sha` to match the assignment contract.

## Alerting Note

Prometheus evaluates the alert rules locally, but this repo does not include Alertmanager wiring. If downstream notification delivery is required, add Alertmanager separately and connect it to Prometheus.
