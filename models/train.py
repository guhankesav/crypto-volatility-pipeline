from __future__ import annotations

import argparse
import json
import math
import os
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import mlflow
import mlflow.sklearn
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.impute import SimpleImputer
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    PrecisionRecallDisplay,
    average_precision_score,
    classification_report,
    f1_score,
    precision_recall_curve,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


# -----------------------------
# Utilities
# -----------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train baseline and ML models for crypto volatility detection")
    parser.add_argument("--features", type=str, required=True, help="Path to labeled features parquet file")
    parser.add_argument("--mlflow_uri", type=str, default="http://localhost:5001", help="MLflow tracking URI")
    parser.add_argument("--experiment", type=str, default="crypto_volatility_detection", help="MLflow experiment name")
    parser.add_argument("--target_col", type=str, default="label_spike", help="Binary target column")
    parser.add_argument("--time_col", type=str, default="exchange_time", help="Timestamp column for time split")
    parser.add_argument("--val_frac", type=float, default=0.2, help="Validation fraction after train split")
    parser.add_argument("--test_frac", type=float, default=0.2, help="Test fraction")
    parser.add_argument("--output_dir", type=str, default="models/artifacts", help="Artifact output directory")
    parser.add_argument("--positive_label", type=int, default=1, help="Positive class label")
    parser.add_argument(
        "--candidate_score_features",
        nargs="*",
        default=[
            "log_return",
            "spread",
            "price",
            "best_bid",
            "best_ask",
            "best_bid_quantity",
            "best_ask_quantity",
            "midprice",
            "sigma_future_60s",
        ],
        help="Candidate columns for z-score baseline selection",
    )
    parser.add_argument(
        "--id_cols",
        nargs="*",
        default=["window_start", "window_end", "event_time", "timestamp", "exchange_time", "ingest_time", "pair", "product_id"],
        help="Columns to exclude from model features",
    )
    parser.add_argument(
        "--leakage_cols",
        nargs="*",
        default=["sigma_future_60s"],
        help="Columns to exclude because they leak future information or are directly derived from the label horizon",
    )
    parser.add_argument(
        "--strict_time_split",
        action="store_true",
        help="Fail instead of falling back if val/test has only one class",
    )
    return parser.parse_args()


@dataclass
class SplitData:
    train_df: pd.DataFrame
    val_df: pd.DataFrame
    test_df: pd.DataFrame
    split_strategy: str


@dataclass
class EvalResult:
    pr_auc: float
    f1_best: float
    threshold_best_f1: float
    precision_at_best_f1: float
    recall_at_best_f1: float
    positives: int
    total: int


# -----------------------------
# Data loading and splitting
# -----------------------------


def load_features(path: str, time_col: str) -> pd.DataFrame:
    df = pd.read_parquet(path)

    if time_col not in df.columns:
        fallback_candidates = ["exchange_time", "ingest_time", "timestamp", "event_time", "time"]
        fallback = next((c for c in fallback_candidates if c in df.columns), None)
        if fallback is None:
            raise ValueError(
                f"time column '{time_col}' not found. Available columns: {list(df.columns)}"
            )
        print(f"Requested time column '{time_col}' not found. Falling back to '{fallback}'.")
        time_col = fallback

    df[time_col] = pd.to_datetime(df[time_col], errors="coerce", utc=True)
    df = df.dropna(subset=[time_col]).sort_values(time_col).reset_index(drop=True)
    df.attrs["resolved_time_col"] = time_col
    return df



def time_split(df: pd.DataFrame, val_frac: float, test_frac: float) -> SplitData:
    n = len(df)
    if n < 50:
        raise ValueError(f"Not enough rows to train reliably. Need at least 50, found {n}.")

    test_start = int((1.0 - test_frac) * n)
    train_val = df.iloc[:test_start].copy()
    test_df = df.iloc[test_start:].copy()

    val_start = int((1.0 - val_frac) * len(train_val))
    train_df = train_val.iloc[:val_start].copy()
    val_df = train_val.iloc[val_start:].copy()

    return SplitData(train_df=train_df, val_df=val_df, test_df=test_df, split_strategy="strict_time")



def stratified_fallback_split(df: pd.DataFrame, target_col: str, val_frac: float, test_frac: float, seed: int = 42) -> SplitData:
    """
    Fallback only for evaluation sanity when strict time split yields zero positives in val/test.
    It preserves time order within each label bucket as much as possible by shuffling minimally.
    """
    pos = df[df[target_col] == 1].copy()
    neg = df[df[target_col] == 0].copy()

    def split_bucket(bucket: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        bucket = bucket.sample(frac=1.0, random_state=seed).reset_index(drop=True)
        n = len(bucket)
        test_n = max(1, int(round(test_frac * n))) if n >= 3 else max(0, int(round(test_frac * n)))
        val_n = max(1, int(round(val_frac * (n - test_n)))) if n - test_n >= 3 else max(0, int(round(val_frac * (n - test_n))))
        test = bucket.iloc[:test_n]
        val = bucket.iloc[test_n:test_n + val_n]
        train = bucket.iloc[test_n + val_n:]
        return train, val, test

    train_pos, val_pos, test_pos = split_bucket(pos)
    train_neg, val_neg, test_neg = split_bucket(neg)

    train_df = pd.concat([train_pos, train_neg]).sample(frac=1.0, random_state=seed).reset_index(drop=True)
    val_df = pd.concat([val_pos, val_neg]).sample(frac=1.0, random_state=seed).reset_index(drop=True)
    test_df = pd.concat([test_pos, test_neg]).sample(frac=1.0, random_state=seed).reset_index(drop=True)

    return SplitData(train_df=train_df, val_df=val_df, test_df=test_df, split_strategy="stratified_fallback")



def ensure_split_has_both_classes(split_data: SplitData, target_col: str, strict: bool) -> SplitData:
    val_unique = split_data.val_df[target_col].nunique()
    test_unique = split_data.test_df[target_col].nunique()

    if val_unique > 1 and test_unique > 1:
        return split_data

    if strict:
        raise ValueError(
            "Strict time split produced validation or test set with only one class. "
            "Either collect more data or rerun without --strict_time_split."
        )

    print("\nWarning: no positives in validation/test with strict time split.")
    print("Using stratified fallback split for meaningful evaluation.\n")

    full_df = pd.concat([split_data.train_df, split_data.val_df, split_data.test_df], ignore_index=True)
    return stratified_fallback_split(
        full_df,
        target_col=target_col,
        val_frac=len(split_data.val_df) / (len(split_data.train_df) + len(split_data.val_df)),
        test_frac=len(split_data.test_df) / len(full_df),
    )


# -----------------------------
# Feature prep
# -----------------------------


def select_feature_columns(
    df: pd.DataFrame,
    target_col: str,
    time_col: str,
    id_cols: List[str],
    leakage_cols: List[str],
) -> List[str]:
    blocked = set(id_cols + leakage_cols + [target_col, time_col])
    numeric_cols = df.select_dtypes(include=[np.number, "bool"]).columns.tolist()
    features = [c for c in numeric_cols if c not in blocked]
    if not features:
        raise ValueError("No numeric feature columns found for training.")
    return features



def build_logreg_pipeline() -> Pipeline:
    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                    solver="liblinear",
                    random_state=42,
                ),
            ),
        ]
    )


def build_random_forest_pipeline() -> Pipeline:
    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            (
                "model",
                RandomForestClassifier(
                    n_estimators=300,
                    max_depth=8,
                    min_samples_leaf=5,
                    class_weight="balanced_subsample",
                    n_jobs=-1,
                    random_state=42,
                ),
            ),
        ]
    )


def build_extra_trees_pipeline() -> Pipeline:
    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            (
                "model",
                ExtraTreesClassifier(
                    n_estimators=300,
                    max_depth=8,
                    min_samples_leaf=5,
                    class_weight="balanced_subsample",
                    n_jobs=-1,
                    random_state=42,
                ),
            ),
        ]
    )


# -----------------------------
# Baseline model
# -----------------------------


def zscore_from_train(train_series: pd.Series, series: pd.Series) -> np.ndarray:
    mu = float(train_series.mean())
    sigma = float(train_series.std(ddof=0))
    sigma = sigma if sigma > 1e-12 else 1.0
    return np.abs((series - mu) / sigma).to_numpy()



def fit_best_zscore_baseline(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    target_col: str,
    candidate_score_features: List[str],
) -> Dict[str, object]:
    usable = [c for c in candidate_score_features if c in train_df.columns and pd.api.types.is_numeric_dtype(train_df[c])]
    if not usable:
        numeric_cols = train_df.select_dtypes(include=[np.number]).columns.tolist()
        usable = [c for c in numeric_cols if c != target_col][:10]

    if not usable:
        raise ValueError("No numeric candidate columns available for z-score baseline.")

    y_val = val_df[target_col].to_numpy()
    best = None

    for col in usable:
        train_s = train_df[col].replace([np.inf, -np.inf], np.nan).fillna(train_df[col].median())
        val_s = val_df[col].replace([np.inf, -np.inf], np.nan).fillna(train_df[col].median())
        scores = zscore_from_train(train_s, val_s)
        pr_auc = average_precision_score(y_val, scores)
        if best is None or pr_auc > best["val_pr_auc"]:
            best = {
                "feature": col,
                "train_mean": float(train_s.mean()),
                "train_std": float(train_s.std(ddof=0)) if float(train_s.std(ddof=0)) > 1e-12 else 1.0,
                "val_pr_auc": float(pr_auc),
            }

    assert best is not None
    return best



def baseline_predict_proba(df: pd.DataFrame, baseline_cfg: Dict[str, object]) -> np.ndarray:
    col = str(baseline_cfg["feature"])
    mu = float(baseline_cfg["train_mean"])
    sigma = float(baseline_cfg["train_std"])
    sigma = sigma if sigma > 1e-12 else 1.0
    x = df[col].replace([np.inf, -np.inf], np.nan).fillna(mu)
    z = np.abs((x - mu) / sigma)
    return z.to_numpy()


# -----------------------------
# Evaluation
# -----------------------------


def evaluate_scores(y_true: np.ndarray, y_score: np.ndarray) -> EvalResult:
    pr_auc = float(average_precision_score(y_true, y_score))
    precision, recall, thresholds = precision_recall_curve(y_true, y_score)

    if len(thresholds) == 0:
        pred = (y_score >= 0.5).astype(int)
        return EvalResult(
            pr_auc=pr_auc,
            f1_best=float(f1_score(y_true, pred, zero_division=0)),
            threshold_best_f1=0.5,
            precision_at_best_f1=0.0,
            recall_at_best_f1=0.0,
            positives=int(y_true.sum()),
            total=len(y_true),
        )

    # precision/recall arrays are one element longer than thresholds
    f1_values = (2 * precision[:-1] * recall[:-1]) / np.clip(precision[:-1] + recall[:-1], 1e-12, None)
    best_idx = int(np.nanargmax(f1_values))
    best_threshold = float(thresholds[best_idx])
    best_pred = (y_score >= best_threshold).astype(int)

    return EvalResult(
        pr_auc=pr_auc,
        f1_best=float(f1_score(y_true, best_pred, zero_division=0)),
        threshold_best_f1=best_threshold,
        precision_at_best_f1=float(precision[best_idx]),
        recall_at_best_f1=float(recall[best_idx]),
        positives=int(y_true.sum()),
        total=len(y_true),
    )



def save_predictions(
    df: pd.DataFrame,
    time_col: str,
    y_true: np.ndarray,
    y_score: np.ndarray,
    out_path: Path,
) -> None:
    keep_cols = [c for c in [time_col, "pair", "product_id"] if c in df.columns]
    out = df[keep_cols].copy()
    out["y_true"] = y_true
    out["score"] = y_score
    out.to_csv(out_path, index=False)


def save_feature_importance_plot(model_pipeline: Pipeline, feature_cols: List[str], out_csv: Path, out_png: Path) -> pd.DataFrame:
    model = model_pipeline.named_steps["model"]
    if not hasattr(model, "feature_importances_"):
        raise ValueError("Model does not expose feature_importances_.")

    importance_df = pd.DataFrame(
        {
            "feature": feature_cols,
            "importance": model.feature_importances_,
        }
    ).sort_values("importance", ascending=False).reset_index(drop=True)

    importance_df.to_csv(out_csv, index=False)

    plt.figure(figsize=(8, 5))
    plt.barh(importance_df["feature"][::-1], importance_df["importance"][::-1])
    plt.xlabel("Feature importance")
    plt.ylabel("Feature")
    plt.title("Random Forest Feature Importance")
    plt.tight_layout()
    plt.savefig(out_png, dpi=200, bbox_inches="tight")
    plt.close()

    return importance_df


def save_pr_curve_plot(curves: List[Dict[str, object]], out_png: Path) -> None:
    plt.figure(figsize=(8, 6))
    for curve in curves:
        precision, recall, _ = precision_recall_curve(curve["y_true"], curve["y_score"])
        pr_auc = average_precision_score(curve["y_true"], curve["y_score"])
        plt.plot(recall, precision, label=f"{curve['name']} (AP={pr_auc:.3f})")

    plt.xlabel("Recall")
    plt.ylabel("Precision")
    plt.title("Precision-Recall Curve on Test Set")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png, dpi=200, bbox_inches="tight")
    plt.close()



def print_label_distribution(split_data: SplitData, target_col: str) -> None:
    print("Label distribution per split:")
    for name, frame in [("Train", split_data.train_df), ("Val", split_data.val_df), ("Test", split_data.test_df)]:
        print(f"{name}:\n", frame[target_col].value_counts(dropna=False).sort_index(), "\n")


# -----------------------------
# Main training flow
# -----------------------------


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading data...")
    df = load_features(args.features, args.time_col)
    args.time_col = df.attrs.get("resolved_time_col", args.time_col)

    if args.target_col not in df.columns:
        raise ValueError(f"Target column '{args.target_col}' not found in features file.")

    df = df.dropna(subset=[args.target_col]).copy()
    df[args.target_col] = df[args.target_col].astype(int)
    if df[args.target_col].nunique() < 2:
        raise ValueError("Target column has only one class in the dataset.")

    split_data = time_split(df, val_frac=args.val_frac, test_frac=args.test_frac)
    split_data = ensure_split_has_both_classes(split_data, args.target_col, strict=args.strict_time_split)
    print_label_distribution(split_data, args.target_col)

    feature_cols = select_feature_columns(
        split_data.train_df,
        target_col=args.target_col,
        time_col=args.time_col,
        id_cols=args.id_cols,
        leakage_cols=args.leakage_cols,
    )

    X_train = split_data.train_df[feature_cols]
    y_train = split_data.train_df[args.target_col].to_numpy()
    X_val = split_data.val_df[feature_cols]
    y_val = split_data.val_df[args.target_col].to_numpy()
    X_test = split_data.test_df[feature_cols]
    y_test = split_data.test_df[args.target_col].to_numpy()

    mlflow.set_tracking_uri(args.mlflow_uri)
    mlflow.set_experiment(args.experiment)

    run_summary: Dict[str, Dict[str, float]] = {}

    # -----------------------------
    # Run 1: z-score baseline
    # -----------------------------
    safe_baseline_features = [c for c in args.candidate_score_features if c not in set(args.leakage_cols)]
    baseline_cfg = fit_best_zscore_baseline(
        train_df=split_data.train_df,
        val_df=split_data.val_df,
        target_col=args.target_col,
        candidate_score_features=safe_baseline_features,
    )

    baseline_val_scores = baseline_predict_proba(split_data.val_df, baseline_cfg)
    baseline_test_scores = baseline_predict_proba(split_data.test_df, baseline_cfg)

    baseline_val_eval = evaluate_scores(y_val, baseline_val_scores)
    baseline_test_eval = evaluate_scores(y_test, baseline_test_scores)

    baseline_cfg_path = out_dir / "baseline_zscore_config.json"
    with open(baseline_cfg_path, "w") as f:
        json.dump(baseline_cfg, f, indent=2)

    baseline_pred_path = out_dir / "baseline_test_predictions.csv"
    save_predictions(split_data.test_df, args.time_col, y_test, baseline_test_scores, baseline_pred_path)

    with mlflow.start_run(run_name="baseline_zscore"):
        mlflow.log_params(
            {
                "model_type": "baseline_zscore",
                "split_strategy": split_data.split_strategy,
                "target_col": args.target_col,
                "time_col": args.time_col,
                "baseline_feature": baseline_cfg["feature"],
                "n_train": len(split_data.train_df),
                "n_val": len(split_data.val_df),
                "n_test": len(split_data.test_df),
            }
        )
        mlflow.log_metrics(
            {
                "val_pr_auc": baseline_val_eval.pr_auc,
                "val_f1_best": baseline_val_eval.f1_best,
                "val_best_threshold": baseline_val_eval.threshold_best_f1,
                "test_pr_auc": baseline_test_eval.pr_auc,
                "test_f1_best": baseline_test_eval.f1_best,
                "test_best_threshold": baseline_test_eval.threshold_best_f1,
            }
        )
        # Some MLflow setups point artifact storage to a read-only location such as /app.
        # Metrics and params will still log correctly, so artifact logging is best-effort.
        try:
            mlflow.log_artifact(str(baseline_cfg_path))
            mlflow.log_artifact(str(baseline_pred_path))
        except OSError as e:
            print(f"Warning: could not log baseline artifacts to MLflow: {e}")
            print("Artifacts are still available in the local output_dir.")

    run_summary["baseline_zscore"] = {
        "val_pr_auc": baseline_val_eval.pr_auc,
        "test_pr_auc": baseline_test_eval.pr_auc,
        "test_f1_best": baseline_test_eval.f1_best,
    }

    # -----------------------------
    # Run 2: Logistic Regression
    # -----------------------------
    logreg = build_logreg_pipeline()
    logreg.fit(X_train, y_train)

    val_scores = logreg.predict_proba(X_val)[:, 1]
    test_scores = logreg.predict_proba(X_test)[:, 1]

    val_eval = evaluate_scores(y_val, val_scores)
    test_eval = evaluate_scores(y_test, test_scores)

    model_path = out_dir / "logreg_pipeline.pkl"
    feature_cols_path = out_dir / "feature_columns.json"
    test_pred_path = out_dir / "logreg_test_predictions.csv"
    report_path = out_dir / "classification_report.txt"

    with open(model_path, "wb") as f:
        pickle.dump(logreg, f)
    with open(feature_cols_path, "w") as f:
        json.dump(feature_cols, f, indent=2)
    save_predictions(split_data.test_df, args.time_col, y_test, test_scores, test_pred_path)

    best_threshold = val_eval.threshold_best_f1
    test_pred = (test_scores >= best_threshold).astype(int)
    report_text = classification_report(y_test, test_pred, digits=4, zero_division=0)
    report_path.write_text(report_text)

    with mlflow.start_run(run_name="logreg_balanced"):
        mlflow.log_params(
            {
                "model_type": "logistic_regression",
                "split_strategy": split_data.split_strategy,
                "target_col": args.target_col,
                "time_col": args.time_col,
                "n_train": len(split_data.train_df),
                "n_val": len(split_data.val_df),
                "n_test": len(split_data.test_df),
                "feature_count": len(feature_cols),
                "class_weight": "balanced",
                "solver": "liblinear",
                "max_iter": 1000,
            }
        )
        mlflow.log_metrics(
            {
                "val_pr_auc": val_eval.pr_auc,
                "val_f1_best": val_eval.f1_best,
                "val_best_threshold": val_eval.threshold_best_f1,
                "test_pr_auc": test_eval.pr_auc,
                "test_f1_best": test_eval.f1_best,
                "test_best_threshold": test_eval.threshold_best_f1,
                "test_precision_best_f1": test_eval.precision_at_best_f1,
                "test_recall_best_f1": test_eval.recall_at_best_f1,
            }
        )
        try:
            mlflow.sklearn.log_model(logreg, artifact_path="model")
            mlflow.log_artifact(str(model_path))
            mlflow.log_artifact(str(feature_cols_path))
            mlflow.log_artifact(str(test_pred_path))
            mlflow.log_artifact(str(report_path))
        except OSError as e:
            print(f"Warning: could not log model artifacts to MLflow: {e}")
            print("Model files are still available in the local output_dir.")

    run_summary["logreg_balanced"] = {
        "val_pr_auc": val_eval.pr_auc,
        "test_pr_auc": test_eval.pr_auc,
        "test_f1_best": test_eval.f1_best,
    }

    # -----------------------------
    # Run 3: Random Forest
    # -----------------------------
    rf = build_random_forest_pipeline()
    rf.fit(X_train, y_train)

    rf_val_scores = rf.predict_proba(X_val)[:, 1]
    rf_test_scores = rf.predict_proba(X_test)[:, 1]

    rf_val_eval = evaluate_scores(y_val, rf_val_scores)
    rf_test_eval = evaluate_scores(y_test, rf_test_scores)

    rf_model_path = out_dir / "random_forest_pipeline.pkl"
    rf_test_pred_path = out_dir / "random_forest_test_predictions.csv"
    rf_report_path = out_dir / "random_forest_classification_report.txt"
    rf_importance_csv_path = out_dir / "random_forest_feature_importance.csv"
    rf_importance_png_path = out_dir / "random_forest_feature_importance.png"

    with open(rf_model_path, "wb") as f:
        pickle.dump(rf, f)
    save_predictions(split_data.test_df, args.time_col, y_test, rf_test_scores, rf_test_pred_path)

    rf_best_threshold = rf_val_eval.threshold_best_f1
    rf_test_pred = (rf_test_scores >= rf_best_threshold).astype(int)
    rf_report_text = classification_report(y_test, rf_test_pred, digits=4, zero_division=0)
    rf_report_path.write_text(rf_report_text)
    rf_importance_df = save_feature_importance_plot(
        rf,
        feature_cols,
        rf_importance_csv_path,
        rf_importance_png_path,
    )

    with mlflow.start_run(run_name="random_forest"):
        mlflow.log_params(
            {
                "model_type": "random_forest",
                "split_strategy": split_data.split_strategy,
                "target_col": args.target_col,
                "time_col": args.time_col,
                "n_train": len(split_data.train_df),
                "n_val": len(split_data.val_df),
                "n_test": len(split_data.test_df),
                "feature_count": len(feature_cols),
                "n_estimators": 300,
                "max_depth": 8,
                "min_samples_leaf": 5,
                "class_weight": "balanced_subsample",
            }
        )
        mlflow.log_metrics(
            {
                "val_pr_auc": rf_val_eval.pr_auc,
                "val_f1_best": rf_val_eval.f1_best,
                "val_best_threshold": rf_val_eval.threshold_best_f1,
                "test_pr_auc": rf_test_eval.pr_auc,
                "test_f1_best": rf_test_eval.f1_best,
                "test_best_threshold": rf_test_eval.threshold_best_f1,
                "test_precision_best_f1": rf_test_eval.precision_at_best_f1,
                "test_recall_best_f1": rf_test_eval.recall_at_best_f1,
            }
        )
        try:
            mlflow.sklearn.log_model(rf, artifact_path="model")
            mlflow.log_artifact(str(rf_model_path))
            mlflow.log_artifact(str(feature_cols_path))
            mlflow.log_artifact(str(rf_test_pred_path))
            mlflow.log_artifact(str(rf_report_path))
            mlflow.log_artifact(str(rf_importance_csv_path))
            mlflow.log_artifact(str(rf_importance_png_path))
        except OSError as e:
            print(f"Warning: could not log random forest artifacts to MLflow: {e}")
            print("Model files are still available in the local output_dir.")

    run_summary["random_forest"] = {
        "val_pr_auc": rf_val_eval.pr_auc,
        "test_pr_auc": rf_test_eval.pr_auc,
        "test_f1_best": rf_test_eval.f1_best,
    }

    # -----------------------------
    # Run 4: Extra Trees
    # -----------------------------
    et = build_extra_trees_pipeline()
    et.fit(X_train, y_train)

    et_val_scores = et.predict_proba(X_val)[:, 1]
    et_test_scores = et.predict_proba(X_test)[:, 1]

    et_val_eval = evaluate_scores(y_val, et_val_scores)
    et_test_eval = evaluate_scores(y_test, et_test_scores)

    et_model_path = out_dir / "extra_trees_pipeline.pkl"
    et_test_pred_path = out_dir / "extra_trees_test_predictions.csv"
    et_report_path = out_dir / "extra_trees_classification_report.txt"

    with open(et_model_path, "wb") as f:
        pickle.dump(et, f)
    save_predictions(split_data.test_df, args.time_col, y_test, et_test_scores, et_test_pred_path)

    et_best_threshold = et_val_eval.threshold_best_f1
    et_test_pred = (et_test_scores >= et_best_threshold).astype(int)
    et_report_text = classification_report(y_test, et_test_pred, digits=4, zero_division=0)
    et_report_path.write_text(et_report_text)

    with mlflow.start_run(run_name="extra_trees"):
        mlflow.log_params(
            {
                "model_type": "extra_trees",
                "split_strategy": split_data.split_strategy,
                "target_col": args.target_col,
                "time_col": args.time_col,
                "n_train": len(split_data.train_df),
                "n_val": len(split_data.val_df),
                "n_test": len(split_data.test_df),
                "feature_count": len(feature_cols),
                "n_estimators": 300,
                "max_depth": 8,
                "min_samples_leaf": 5,
                "class_weight": "balanced_subsample",
            }
        )
        mlflow.log_metrics(
            {
                "val_pr_auc": et_val_eval.pr_auc,
                "val_f1_best": et_val_eval.f1_best,
                "val_best_threshold": et_val_eval.threshold_best_f1,
                "test_pr_auc": et_test_eval.pr_auc,
                "test_f1_best": et_test_eval.f1_best,
                "test_best_threshold": et_test_eval.threshold_best_f1,
                "test_precision_best_f1": et_test_eval.precision_at_best_f1,
                "test_recall_best_f1": et_test_eval.recall_at_best_f1,
            }
        )
        try:
            mlflow.sklearn.log_model(et, artifact_path="model")
            mlflow.log_artifact(str(et_model_path))
            mlflow.log_artifact(str(feature_cols_path))
            mlflow.log_artifact(str(et_test_pred_path))
            mlflow.log_artifact(str(et_report_path))
        except OSError as e:
            print(f"Warning: could not log extra trees artifacts to MLflow: {e}")
            print("Model files are still available in the local output_dir.")

    run_summary["extra_trees"] = {
        "val_pr_auc": et_val_eval.pr_auc,
        "test_pr_auc": et_test_eval.pr_auc,
        "test_f1_best": et_test_eval.f1_best,
    }

    pr_curve_path = out_dir / "test_precision_recall_curve.png"
    save_pr_curve_plot(
        curves=[
            {"name": "baseline_zscore", "y_true": y_test, "y_score": baseline_test_scores},
            {"name": "logreg_balanced", "y_true": y_test, "y_score": test_scores},
            {"name": "random_forest", "y_true": y_test, "y_score": rf_test_scores},
            {"name": "extra_trees", "y_true": y_test, "y_score": et_test_scores},
        ],
        out_png=pr_curve_path,
    )

    print("Top Random Forest features:")
    print(rf_importance_df.to_string(index=False))
    print(f"Saved feature importance CSV to: {rf_importance_csv_path}")
    print(f"Saved feature importance plot to: {rf_importance_png_path}")
    print(f"Saved PR curve plot to: {pr_curve_path}")

    # -----------------------------
    # Save summary
    # -----------------------------
    summary = {
        "features_path": args.features,
        "split_strategy": split_data.split_strategy,
        "target_col": args.target_col,
        "time_col": args.time_col,
        "rows": {
            "train": len(split_data.train_df),
            "val": len(split_data.val_df),
            "test": len(split_data.test_df),
        },
        "positive_rate": {
            "train": float(split_data.train_df[args.target_col].mean()),
            "val": float(split_data.val_df[args.target_col].mean()),
            "test": float(split_data.test_df[args.target_col].mean()),
        },
        "runs": run_summary,
        "feature_columns": feature_cols,
        "excluded_leakage_columns": args.leakage_cols,
        "random_forest_feature_importance": rf_importance_df.to_dict(orient="records"),
        "best_model_by_test_pr_auc": max(run_summary.items(), key=lambda kv: kv[1]["test_pr_auc"])[0],
    }

    summary_path = out_dir / "training_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print("Training complete.")
    print(json.dumps(summary, indent=2))
    print(f"Artifacts saved to: {out_dir.resolve()}")


if __name__ == "__main__":
    main()