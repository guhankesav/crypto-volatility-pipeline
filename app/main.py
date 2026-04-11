import os
import pickle
import time

import pandas as pd
from fastapi import FastAPI, HTTPException, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel

APP_VERSION = os.getenv("APP_VERSION", "week4-thin-slice-v1")
MODEL_NAME = os.getenv("MODEL_NAME", "random_forest")
MODEL_PATH = os.getenv("MODEL_PATH", "/app/models/artifacts/random_forest.pkl")

app = FastAPI(title="Crypto Volatility API", version=APP_VERSION)

predict_requests = Counter("predict_requests_total", "Total prediction requests")
predict_errors = Counter("predict_errors_total", "Total prediction failures")
predict_latency = Histogram("predict_latency_seconds", "Prediction latency")

model = None

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


class PredictRequest(BaseModel):
    price: float | None = None
    best_bid: float
    best_ask: float
    best_bid_quantity: float | None = None
    best_ask_quantity: float | None = None
    log_return: float | None = None
    product_id: str = "BTC-USD"


def load_model():
    global model
    if model is None:
        with open(MODEL_PATH, "rb") as f:
            model = pickle.load(f)
    return model


def build_features(payload: PredictRequest) -> pd.DataFrame:
    midprice = (payload.best_bid + payload.best_ask) / 2.0
    spread = payload.best_ask - payload.best_bid
    row = {
        "price": payload.price,
        "best_bid": payload.best_bid,
        "best_ask": payload.best_ask,
        "best_bid_quantity": payload.best_bid_quantity,
        "best_ask_quantity": payload.best_ask_quantity,
        "midprice": midprice,
        "spread": spread,
        "log_return": payload.log_return,
    }
    return pd.DataFrame([row], columns=FEATURE_COLUMNS)


@app.get("/health")
def health():
    try:
        load_model()
        return {"status": "ok", "model_loaded": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/version")
def version():
    return {
        "service": "crypto-volatility-api",
        "version": APP_VERSION,
        "model_name": MODEL_NAME,
    }


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/predict")
def predict(req: PredictRequest):
    start = time.perf_counter()
    predict_requests.inc()
    try:
        clf = load_model()
        X = build_features(req)
        if hasattr(clf, "predict_proba"):
            probability = float(clf.predict_proba(X)[0][1])
        else:
            probability = float(clf.predict(X)[0])
        prediction = int(probability >= 0.5)
        predict_latency.observe(time.perf_counter() - start)
        return {
            "model_version": APP_VERSION,
            "prediction": prediction,
            "probability": probability,
        }
    except Exception as e:
        predict_errors.inc()
        raise HTTPException(status_code=500, detail=str(e))