# Model Selection Rationale

## 17-313 Real-Time Crypto AI Service

## 1. Overview

We selected a **Random Forest model** as the primary model for our real-time crypto volatility detection system.

The task is to predict whether **volatility in the next 60 seconds exceeds a threshold**, using live Coinbase data streamed through Kafka.

## 2. Problem Definition

We frame this as a binary classification problem:

- **1 (spike):** future 60s volatility ≥ τ  
- **0 (normal):** otherwise  

Where:
- Volatility = standard deviation of log returns over the next 60 seconds  
- Threshold τ = 95th percentile of the volatility distribution  

This aligns with the repository’s labeling pipeline (`horizon_seconds=60`, `tau_quantile=0.95`).

## 3. Metrics

Due to class imbalance (~5% spikes):

- **Primary:** PR-AUC  
- **Secondary:** F1-score  

Both are implemented in `models/train.py` using precision-recall evaluation.

## 4. Models Evaluated

The training pipeline compares:

- Z-score baseline  
- Logistic Regression  
- Random Forest  
- Extra Trees  

Training uses a **time-based split**, with a **stratified fallback** when needed to ensure both classes are present.

## 5. Model Choice: Random Forest

We selected **Random Forest** based on performance, problem fit, and system alignment.

### Performance  
Tree-based models significantly outperform linear and rule-based approaches. Random Forest consistently achieves the strongest results, indicating it captures meaningful structure in the data.

Model selection in this repository is dynamic (`training_summary.json`), but Random Forest is currently the best-performing and default model.

### Non-Linearity  
Volatility prediction depends on interactions between order book and price features. Random Forest effectively captures these **non-linear relationships**, unlike Logistic Regression.

### System Alignment  
The inference pipeline (`models/infer.py`) defaults to:
models/artifacts/random_forest_pipeline.pkl

This confirms Random Forest is the **production model** used in the system.

### Real-Time Feasibility  
Random Forest meets latency and throughput requirements and integrates cleanly with the Kafka + FastAPI pipeline.

## 6. Features

Features generated in `features/featurizer.py` include:

- midprice  
- bid/ask prices and quantities  
- price  
- spread  
- log return  

These are:
- computed in real time  
- lightweight  
- reflective of market microstructure  

### Leakage Handling

`sigma_future_60s` is excluded from model inputs because it depends on future data.

This is enforced in:
- `models/train.py` (`--leakage_cols`)  
- `models/infer.py` (`DEFAULT_EXCLUDED`)  

## 7. Deployment Strategy

We support two model variants:

- `ml` → Random Forest (primary)  
- `baseline` → rule-based fallback  

This enables rollback and safer deployment.

## 8. Configuration Note

`config.yaml` references Logistic Regression, but this is outdated.

The actual source of truth for model selection is:
- `models/train.py` (training + evaluation)  
- `models/infer.py` (serving default)  

## 9. Tradeoffs

**Benefits:**
- Strong predictive performance  
- Captures non-linear relationships  
- Works effectively in a real-time system  

**Tradeoffs:**
- Less interpretable than linear models  
- Performance may vary across datasets (e.g., Extra Trees may outperform in some runs)  

## 10. Final Decision

Random Forest is the best choice because it:
- Performs strongest on this task  
- Matches the data’s non-linear structure  
- Aligns with the repository’s inference pipeline  
- Meets real-time system constraints  


