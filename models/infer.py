from __future__ import annotations

import argparse
import json
import pickle
import time
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd


DEFAULT_EXCLUDED = [
    "window_start",
    "window_end",
    "event_time",
    "timestamp",
    "exchange_time",
    "ingest_time",
    "pair",
    "product_id",
    "label_spike",
    "sigma_future_60s",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inference for crypto volatility detection")
    parser.add_argument("--features", type=str, required=True, help="Path to parquet/csv feature file")
    parser.add_argument(
        "--model_path",
        type=str,
        default="models/artifacts/random_forest_pipeline.pkl",
        help="Path to trained sklearn pipeline",
    )
    parser.add_argument(
        "--feature_cols_path",
        type=str,
        default="models/artifacts/feature_columns.json",
        help="Path to saved feature column list",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Decision threshold for binary predictions",
    )
    parser.add_argument(
        "--output_path",
        type=str,
        default="models/artifacts/inference_predictions.csv",
        help="Where to save inference output",
    )
    parser.add_argument(
        "--time_col",
        type=str,
        default="exchange_time",
        help="Timestamp column to preserve in output if present",
    )
    parser.add_argument(
        "--id_cols",
        nargs="*",
        default=["product_id", "pair"],
        help="Optional identifier columns to preserve in output if present",
    )
    return parser.parse_args()


def load_input(path: str) -> pd.DataFrame:
    path_obj = Path(path)
    if not path_obj.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    if path_obj.suffix == ".parquet":
        return pd.read_parquet(path_obj)
    if path_obj.suffix == ".csv":
        return pd.read_csv(path_obj)

    raise ValueError("Unsupported input format. Use parquet or csv.")


def load_feature_columns(feature_cols_path: str, df: pd.DataFrame) -> List[str]:
    path_obj = Path(feature_cols_path)
    if path_obj.exists():
        with open(path_obj, "r") as f:
            feature_cols = json.load(f)
        missing = [c for c in feature_cols if c not in df.columns]
        if missing:
            raise ValueError(f"Missing expected feature columns at inference time: {missing}")
        return feature_cols

    numeric_cols = df.select_dtypes(include=[np.number, "bool"]).columns.tolist()
    feature_cols = [c for c in numeric_cols if c not in DEFAULT_EXCLUDED]
    if not feature_cols:
        raise ValueError("Could not infer feature columns from input file.")
    return feature_cols


def main() -> None:
    args = parse_args()

    input_df = load_input(args.features)

    if args.time_col in input_df.columns:
        input_df[args.time_col] = pd.to_datetime(input_df[args.time_col], errors="coerce", utc=True)

    feature_cols = load_feature_columns(args.feature_cols_path, input_df)

    with open(args.model_path, "rb") as f:
        model = pickle.load(f)

    X = input_df[feature_cols].copy()

    start = time.perf_counter()
    scores = model.predict_proba(X)[:, 1]
    elapsed = time.perf_counter() - start

    preds = (scores >= args.threshold).astype(int)

    keep_cols = [c for c in [args.time_col] + args.id_cols if c in input_df.columns]
    out_df = input_df[keep_cols].copy()
    out_df["score"] = scores
    out_df["prediction"] = preds
    out_df["threshold"] = args.threshold

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(output_path, index=False)

    throughput = len(input_df) / elapsed if elapsed > 0 else float("inf")
    avg_ms = (elapsed / max(len(input_df), 1)) * 1000.0

    summary = {
        "rows_scored": int(len(input_df)),
        "model_path": args.model_path,
        "feature_cols_path": args.feature_cols_path,
        "num_features": int(len(feature_cols)),
        "threshold": float(args.threshold),
        "elapsed_seconds": float(elapsed),
        "rows_per_second": float(throughput),
        "avg_latency_ms_per_row": float(avg_ms),
        "output_path": str(output_path),
    }

    summary_path = output_path.with_suffix(".summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print("Inference complete.")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
