from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from evidently import Report
from evidently.presets import DataDriftPreset, DataSummaryPreset


FEATURES_PATH = "data/processed/features_labeled.parquet"
OUTPUT_HTML = "reports/evidently_report.html"
OUTPUT_JSON = "reports/evidently_report.json"
SUMMARY_JSON = "models/artifacts/training_summary.json"
TIME_COL = "exchange_time"


def load_data(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df[TIME_COL] = pd.to_datetime(df[TIME_COL], errors="coerce", utc=True)
    df = df.dropna(subset=[TIME_COL]).sort_values(TIME_COL).reset_index(drop=True)

    # avoid timezone-related plotting/export issues
    if isinstance(df[TIME_COL].dtype, pd.DatetimeTZDtype):
        df[TIME_COL] = df[TIME_COL].dt.tz_convert(None)

    return df


def make_split(df: pd.DataFrame):
    with open(SUMMARY_JSON, "r") as f:
        summary = json.load(f)

    n_train = summary["rows"]["train"]
    n_val = summary["rows"]["val"]

    train_df = df.iloc[:n_train].copy()
    test_df = df.iloc[n_train + n_val :].copy()
    return train_df, test_df


def export_snapshot(snapshot, html_path: str, json_path: str) -> None:
    if hasattr(snapshot, "save_html"):
        snapshot.save_html(html_path)
        return

    if hasattr(snapshot, "save_json"):
        snapshot.save_json(json_path)
        return

    if hasattr(snapshot, "json"):
        Path(json_path).write_text(snapshot.json(), encoding="utf-8")
        return

    if hasattr(snapshot, "dict"):
        Path(json_path).write_text(
            json.dumps(snapshot.dict(), indent=2),
            encoding="utf-8",
        )
        return

    raise AttributeError(
        "Could not export Evidently result. No save_html(), save_json(), json(), or dict() method found."
    )


def main():
    Path("reports").mkdir(parents=True, exist_ok=True)

    df = load_data(FEATURES_PATH)
    train_df, test_df = make_split(df)

    for col in ["sigma_future_60s"]:
        if col in train_df.columns:
            train_df = train_df.drop(columns=[col])
            test_df = test_df.drop(columns=[col])

    report = Report(
        metrics=[
            DataSummaryPreset(),
            DataDriftPreset(),
        ]
    )

    snapshot = report.run(reference_data=train_df, current_data=test_df)
    export_snapshot(snapshot, OUTPUT_HTML, OUTPUT_JSON)

    if Path(OUTPUT_HTML).exists():
        print(f"Saved Evidently HTML report to: {OUTPUT_HTML}")
    else:
        print(f"Saved Evidently JSON report to: {OUTPUT_JSON}")

if __name__ == "__main__":
    main()


