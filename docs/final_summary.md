# Final Metrics Summary

## Latency (100-burst load test)

Source: `docs/latency_report.md` (`MODEL_VARIANT=baseline`, 100 concurrent `POST /predict`).

- p50: **60.0 ms**
- p95: **62.4 ms** (SLO target: <= 800 ms)
- p99: **63.0 ms**
- outcome: **SLO OK**

## Uptime / Availability (observed demo test window)

Source: API Prometheus counters during the same burst test.

- `predict_requests_total`: **100**
- `predict_errors_total`: **0**
- observed success rate in window: **100%** (`(100 - 0) / 100`)

This is an observed run-window summary, not a long-horizon SLI.

## PR-AUC vs Baseline

Source: `reports/model_eval.txt` (test split).

- baseline PR-AUC: **0.056699**
- logistic regression PR-AUC: **0.106697**
- absolute lift: **+0.049998**
- relative lift: **~88.2%** over baseline

## Notes

- SLO targets and PromQL definitions are documented in `docs/slo.md`.
- Drift artifacts are in `reports/evidently_report.html` and `reports/evidently_report.json`.
