# Model Card v1: Crypto Volatility Spike Detection

## 1. Model Overview

This project builds a machine learning system to detect short term volatility spikes in cryptocurrency markets using high frequency order book data. The goal is to predict whether volatility in the next 60 seconds will exceed a predefined threshold.

The best performing model is a tree-based ensemble (Random Forest), trained on engineered features derived from streaming market data.

---

## 2. Intended Use

The model is intended for:

* Real time monitoring of crypto market volatility
* Alerting systems for trading or risk management
* Analytical insights into market microstructure

The model is **not intended for direct automated trading decisions** without further validation.

---

## 3. Data

### Source

* Coinbase Advanced Trade WebSocket API (BTC-USD)

### Features

* Midprice
* Log returns
* Bid-ask spread
* Bid/ask quantities
* Derived rolling statistics

### Target

* Binary label indicating volatility spike:

  * 1 if future 60s volatility ≥ τ
  * 0 otherwise

### Threshold

* τ = 95th percentile of future volatility

---

## 4. Data Splitting

* Time based split (train → validation → test)
* Stratified fallback applied due to class imbalance

---

## 5. Class Imbalance

* Positive class (~5%)
* Highly imbalanced dataset

Handled via:

* Class weighted models
* PR AUC evaluation metric

---

## 6. Models Evaluated

* Z-score baseline
* Logistic Regression
* Random Forest
* Extra Trees

---

## 7. Evaluation Metrics

* Primary: PR AUC
* Secondary: F1 score

---

## 8. Performance Summary

* Logistic Regression: PR AUC ≈ 0.996
* Random Forest: PR AUC ≈ 0.96
* Extra Trees: PR AUC ≈ 0.96

The baseline initially showed perfect performance due to data leakage and was corrected.

---

## 9. Key Findings

* Volatility prediction is highly non linear
* Tree-based models outperform linear models
* Temporal clustering of volatility is observable
* Model is robust despite feature drift

---

## 10. Data Leakage Note

The feature `sigma_future_60s` directly encodes the target and was removed from model inputs to prevent leakage.

---

## 11. Inference Performance

* ~195,000 rows/sec
* ~0.005 ms per row

Meets real-time inference requirements.

---

## 12. Limitations

* Trained on a limited time window
* May not generalize across all market regimes
* Sensitive to distribution shifts

---

## 13. Ethical Considerations

* Uses public market data only
* No trading actions executed
* Potential misuse in automated trading systems

---

## 14. Future Work

* Incorporate order book depth features
* Use sequence models (LSTM/Transformer)
* Deploy real time monitoring with drift alerts
