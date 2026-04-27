from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from evidently import Report
from evidently.presets import DataDriftPreset, DataSummaryPreset


DEFAULT_REFERENCE = "models/artifacts/logreg_test_predictions.csv"
DEFAULT_CURRENT = "models/artifacts/random_forest_test_predictions.csv"
DEFAULT_HTML = "reports/evidently_report.html"
DEFAULT_JSON = "reports/evidently_report.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an Evidently drift report.")
    parser.add_argument("--reference", default=DEFAULT_REFERENCE, help="Reference dataset path (CSV or Parquet).")
    parser.add_argument("--current", default=DEFAULT_CURRENT, help="Current dataset path (CSV or Parquet).")
    parser.add_argument("--output-html", default=DEFAULT_HTML, help="Output HTML report path.")
    parser.add_argument("--output-json", default=DEFAULT_JSON, help="Output JSON report path.")
    return parser.parse_args()


def load_dataset(path_str: str) -> pd.DataFrame:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".parquet":
        return pd.read_parquet(path)

    raise ValueError(f"Unsupported dataset format for {path}. Use CSV or Parquet.")


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    for column in normalized.columns:
        if "time" in column.lower():
            parsed = pd.to_datetime(normalized[column], errors="coerce", utc=True)
            if parsed.notna().any():
                normalized[column] = parsed.astype(str)
    return normalized


def select_common_columns(reference_df: pd.DataFrame, current_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    common_columns = [column for column in reference_df.columns if column in current_df.columns]
    if not common_columns:
        raise ValueError("Reference and current datasets do not share any columns.")
    return reference_df[common_columns].copy(), current_df[common_columns].copy()


def export_snapshot(snapshot, html_path: Path, json_path: Path) -> None:
    html_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    if hasattr(snapshot, "save_html"):
        snapshot.save_html(str(html_path))
    if hasattr(snapshot, "save_json"):
        snapshot.save_json(str(json_path))
        return
    if hasattr(snapshot, "json"):
        json_path.write_text(snapshot.json(), encoding="utf-8")
        return
    if hasattr(snapshot, "dict"):
        json_path.write_text(json.dumps(snapshot.dict(), indent=2), encoding="utf-8")
        return
    raise AttributeError("Unable to export Evidently snapshot in JSON format.")


def main() -> int:
    args = parse_args()
    try:
        reference_df = normalize_dataframe(load_dataset(args.reference))
        current_df = normalize_dataframe(load_dataset(args.current))
        reference_df, current_df = select_common_columns(reference_df, current_df)

        report = Report(metrics=[DataSummaryPreset(), DataDriftPreset()])
        snapshot = report.run(reference_data=reference_df, current_data=current_df)
        export_snapshot(snapshot, Path(args.output_html), Path(args.output_json))

        print(f"Reference dataset: {args.reference}")
        print(f"Current dataset:   {args.current}")
        print(f"Saved HTML report: {args.output_html}")
        print(f"Saved JSON report: {args.output_json}")
        return 0
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Unable to generate drift report: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
