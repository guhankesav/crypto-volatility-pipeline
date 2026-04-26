from __future__ import annotations

import json
import math
import os
import pickle
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field

APP_VERSION = os.getenv("APP_VERSION", "v1.2")
MODEL_NAME = os.getenv("MODEL_NAME", "random_forest")
MODEL_PATH = os.getenv("MODEL_PATH", "/app/models/artifacts/random_forest_pipeline.pkl")
MODEL_VARIANT = os.getenv("MODEL_VARIANT", "ml").strip().lower()
GIT_SHA = os.getenv("GIT_SHA", "unknown")
BASELINE_CONFIG_PATH = os.getenv(
    "BASELINE_CONFIG_PATH",
    "/app/models/artifacts/baseline_zscore_config.json",
)

FEATURE_COLUMNS = [
    "price",
    "best_bid",
    "best_ask",
    "best_bid_quantity",
    "best_ask_quantity",
    "midprice",
    "spread",
    "log_return",
]

app = FastAPI(title="Crypto Volatility API", version=APP_VERSION)

predict_requests = Counter("predict_requests_total", "Total prediction requests")
predict_errors = Counter("predict_errors_total", "Total prediction failures")
predict_latency = Histogram(
    "predict_latency_seconds",
    "Prediction latency in seconds",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.8, 1.0, 2.0, 5.0),
)
last_prediction_timestamp = Gauge(
    "last_prediction_timestamp_seconds",
    "Unix timestamp of the most recent successful prediction",
)


class PredictRow(BaseModel):
    ret_mean: float
    ret_std: float
    n: int = Field(gt=0)


class PredictRequest(BaseModel):
    rows: list[PredictRow]


@dataclass
class ModelRuntime:
    variant: str
    model_name: str
    predictor: Any | None = None
    baseline_cfg: dict[str, Any] | None = None


runtime: ModelRuntime | None = None


def sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def load_pickle(path: str) -> Any:
    with open(path, "rb") as file_obj:
        return pickle.load(file_obj)


def load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


def get_model_runtime() -> ModelRuntime:
    global runtime

    if runtime is not None:
        return runtime

    if MODEL_VARIANT not in {"ml", "baseline"}:
        raise RuntimeError("MODEL_VARIANT must be one of: ml, baseline")

    if MODEL_VARIANT == "ml":
        runtime = ModelRuntime(
            variant="ml",
            model_name=MODEL_NAME,
            predictor=load_pickle(MODEL_PATH),
        )
        return runtime

    baseline_cfg = None
    baseline_path = Path(BASELINE_CONFIG_PATH)
    if baseline_path.exists():
        baseline_cfg = load_json(str(baseline_path))

    runtime = ModelRuntime(
        variant="baseline",
        model_name="deterministic_baseline",
        baseline_cfg=baseline_cfg,
    )
    return runtime


def build_ml_features(rows: list[PredictRow]) -> pd.DataFrame:
    base_price = 70_000.0
    records: list[dict[str, float]] = []

    for row in rows:
        ret_mean = float(row.ret_mean)
        ret_std = max(float(row.ret_std), 0.0)
        count = max(int(row.n), 1)

        midprice = base_price * (1.0 + ret_mean)
        spread = min(max(base_price * max(ret_std, 1e-6) * 0.001, 0.01), 5.0)
        best_bid = midprice - (spread / 2.0)
        best_ask = midprice + (spread / 2.0)
        qty_base = min(max(count / 1000.0, 1e-6), 4.0)

        records.append(
            {
                "price": midprice * (1.0 + (ret_mean / 2.0)),
                "best_bid": best_bid,
                "best_ask": best_ask,
                "best_bid_quantity": qty_base,
                "best_ask_quantity": min(max(qty_base * (1.0 + (ret_std * 10.0)), 1e-6), 4.0),
                "midprice": midprice,
                "spread": spread,
                "log_return": ret_mean,
            }
        )

    return pd.DataFrame.from_records(records, columns=FEATURE_COLUMNS)


def score_ml(rows: list[PredictRow], predictor: Any) -> list[float]:
    features = build_ml_features(rows)
    if hasattr(predictor, "predict_proba"):
        scores = predictor.predict_proba(features)[:, 1]
    else:
        scores = predictor.predict(features)
    return [float(score) for score in scores]


def score_baseline(rows: list[PredictRow], baseline_cfg: dict[str, Any] | None) -> list[float]:
    scores: list[float] = []
    cfg_mean = float((baseline_cfg or {}).get("train_mean", 0.07))
    cfg_std = max(float((baseline_cfg or {}).get("train_std", 0.13)), 1e-6)

    for row in rows:
        magnitude = (abs(float(row.ret_mean)) * 6.0) + (max(float(row.ret_std), 0.0) * math.sqrt(row.n) * 12.0) - 0.2
        heuristic = sigmoid(magnitude)

        # If a trained baseline config exists, blend it in using a real repo artifact.
        synthetic_quantity = min(max(row.n / 1000.0, 1e-6), 4.0)
        zscore = abs((synthetic_quantity - cfg_mean) / cfg_std)
        blended = 0.7 * heuristic + 0.3 * sigmoid(zscore - 1.0)
        scores.append(float(min(max(blended, 0.0), 1.0)))

    return scores


def score_rows(rows: list[PredictRow]) -> tuple[list[float], str]:
    current_runtime = get_model_runtime()

    if current_runtime.variant == "ml":
        assert current_runtime.predictor is not None
        return score_ml(rows, current_runtime.predictor), current_runtime.variant

    return score_baseline(rows, current_runtime.baseline_cfg), current_runtime.variant


@app.get("/health")
def health() -> dict[str, str]:
    try:
        get_model_runtime()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok"}


@app.get("/version")
def version() -> dict[str, str]:
    return {
        "model": MODEL_NAME,
        "sha": GIT_SHA,
    }


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/predict")
def predict(request: PredictRequest) -> dict[str, Any]:
    start = time.perf_counter()
    predict_requests.inc()

    try:
        scores, variant = score_rows(request.rows)
        last_prediction_timestamp.set(time.time())
        return {
            "scores": scores,
            "model_variant": variant,
            "version": APP_VERSION,
            "ts": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }
    except Exception as exc:
        predict_errors.inc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        predict_latency.observe(time.perf_counter() - start)
