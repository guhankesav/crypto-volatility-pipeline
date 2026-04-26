"""Integration tests for the FastAPI app using baseline model (no pickle required)."""
from __future__ import annotations

import os

os.environ.setdefault("MODEL_VARIANT", "baseline")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_predict_returns_valid_score():
    payload = {"rows": [{"ret_mean": 0.05, "ret_std": 0.01, "n": 50}]}
    response = client.post("/predict", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "scores" in data
    assert len(data["scores"]) == 1
    score = data["scores"][0]
    assert 0.0 <= score <= 1.0
    assert data["model_variant"] == "baseline"
    assert "version" in data
    assert "ts" in data


def test_predict_multiple_rows():
    payload = {
        "rows": [
            {"ret_mean": 0.0, "ret_std": 0.0, "n": 1},
            {"ret_mean": 0.2, "ret_std": 0.1, "n": 200},
        ]
    }
    response = client.post("/predict", json=payload)
    assert response.status_code == 200
    scores = response.json()["scores"]
    assert len(scores) == 2
    assert all(0.0 <= s <= 1.0 for s in scores)
    # High volatility row should score higher than low volatility row
    assert scores[1] > scores[0]


def test_predict_invalid_payload_returns_422():
    response = client.post("/predict", json={"rows": [{"ret_mean": 0.1}]})
    assert response.status_code == 422
