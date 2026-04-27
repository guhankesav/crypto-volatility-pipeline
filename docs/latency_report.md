# Load test — burst latency (100 concurrent `/predict`)

## Method

- **Script:** `tests/load_test.py` (default: **100** concurrent `POST /predict` with the same small JSON body).
- **SLO (from** `docs/slo.md` **/ load script):** p95 **≤ 800 ms**; script exits with code 1 if p95 is above the SLO.
- **Reproduce (terminal 1):**
  - `export MODEL_VARIANT=baseline`
  - `uvicorn app.main:app --host 127.0.0.1 --port 8000`
- **Reproduce (terminal 2), from repo root:**
  - `python tests/load_test.py --url http://127.0.0.1:8000 --n 100`

## Results (baseline API, same machine as test client)

Last measured: 2026-04-26 (`python tests/load_test.py --url http://127.0.0.1:8000 --n 100`)

| Metric | Value (ms) |
|--------|------------|
| Requests ok | 100 |
| Errors | 0 |
| Min | 48.6 |
| p50 | 60.0 |
| **p95** | 62.4 (SLO: ≤ 800) |
| p99 | 63.0 |
| Max | 63.0 |
| StdDev | 4.0 |

**Outcome:** SLO OK.

**Notes:** Latency is sensitive to machine load, `MODEL_VARIANT` (`baseline` vs `ml`), and whether the process is colocated with the client. Re-run after dependency or API changes; update this file when you submit a milestone.
