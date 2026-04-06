# Crypto Volatility Spike Detection (Real-Time)

## Overview
This project implements an end-to-end real-time pipeline for detecting short-term volatility spikes in cryptocurrency markets using streaming data.

The system ingests live market data from Coinbase WebSocket, processes it using Kafka, generates features, trains machine learning models, and evaluates performance using MLflow and Evidently.

The prediction task is to determine whether volatility in the next 60 seconds exceeds a threshold.

---

## Problem Definition
Given market observations up to time t, predict:

Volatility spike in (t, t + 60s]

This is formulated as a binary classification problem.

Evaluation Metric:
- Primary: PR-AUC (due to class imbalance)
- Secondary: F1-score

---

## System Architecture

WebSocket → Kafka (`ticks.raw`) → Feature Pipeline → Kafka (`ticks.features`)
→ Parquet Storage → Model Training → MLflow → Evaluation + Evidently

---

## Repository Structure

/data/raw/               Raw streamed data  
/data/processed/         Feature dataset  
/features/               Feature engineering pipeline  
/models/                 Training, inference, artifacts  
/notebooks/              EDA analysis  
/reports/                Evaluation + drift reports  
/scripts/                Ingestion + replay + validation  
/docker/                 Docker Compose + Dockerfile  
/docs/                   Feature spec, model card, GenAI log  
/handoff/                Submission bundle  
requirements.txt  
README.md  

---

## Milestone Breakdown

### Milestone 1: Streaming Setup
- Kafka + MLflow via Docker
- WebSocket ingestion (Coinbase)
- Data published to `ticks.raw`

### Milestone 2: Feature Engineering & EDA
- Features computed from streaming data:
  - midprice
  - spread
  - log return
  - order book features
- Output to `ticks.features`
- Replay pipeline ensures deterministic features
- Evidently report for drift analysis

### Milestone 3: Modeling & Evaluation
- Baseline: Z-score rule
- ML models:
  - Logistic Regression
  - Random Forest
  - Extra Trees
- Metrics:
  - PR-AUC
  - F1-score
- MLflow tracking for experiments

---

## How to Run

### 1. Start services
docker compose up -d

### 2. Ingest data
python scripts/ws_ingest.py --pair BTC-USD --minutes 15

### 3. Validate Kafka stream
python scripts/kafka_consume_check.py --topic ticks.raw --min 100

### 4. Generate features
python features/featurizer.py --topic_in ticks.raw --topic_out ticks.features

### 5. Replay pipeline
python scripts/replay.py --raw data/raw/*.ndjson --out data/processed/features.parquet

### 6. Train models
python models/train.py --features data/processed/features.parquet

### 7. Run inference
python models/infer.py --features data/processed/features_test.parquet

---

## Key Results

- Random Forest achieved highest PR-AUC (~0.96)
- Tree-based models outperform linear models
- Volatility prediction is non-linear
- Model meets real-time inference constraints

---

## Data Drift Analysis

Evidently report compares:
- Early (training) vs late (test) data

Findings:
- ~70% of features show drift
- Core features remain stable
- Model generalizes well across time

---

## Inference Performance

- ~195,000 rows/sec
- ~0.005 ms per row
- Meets <2x real-time requirement

---

## Handoff

The `/handoff/` folder contains:
- Docker setup
- Model artifacts
- Feature spec + model card
- Sample data + predictions
- Reports (evaluation + drift)

---

## GenAI Usage

Details are documented in:
docs/genai_appendix.md

---

## Conclusion

This project demonstrates a production-style pipeline integrating:
- Streaming ingestion
- Feature engineering
- Model training and evaluation
- Drift monitoring

The system successfully detects volatility spikes in real time.
