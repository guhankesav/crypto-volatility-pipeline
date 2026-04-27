# Drift Summary

## Datasets Used

- Reference dataset: `models/artifacts/logreg_test_predictions.csv`
- Current dataset: `models/artifacts/random_forest_test_predictions.csv`

The new drift script also supports CSV and Parquet inputs through command-line flags:

```bash
python scripts/generate_drift_report.py --reference path/to/reference.csv --current path/to/current.parquet
```

## Features Monitored

The default report monitors the shared columns between the reference and current datasets:

- `exchange_time`
- `product_id`
- `y_true`
- `score`

## Drift Results

- The generated Evidently report compares the score distribution from the logistic-regression reference output against the random-forest current output.
- `product_id` and `y_true` are expected to stay relatively stable because they come from the same labeled evaluation slice.
- `score` is the main signal to watch and is expected to show noticeable distribution shift because the two models produce very different confidence patterns.

## Interpretation

- Low drift: distributions are similar and monitoring can continue without immediate action.
- Medium drift: review the affected features, compare recent prediction samples, and watch SLOs closely.
- High drift: inspect model behavior, data collection changes, and consider rollback if drift coincides with elevated errors or latency.

## Action Plan

- Low drift: continue monitoring and keep the current model variant.
- Medium drift: review recent input samples, confirm feature generation is stable, and compare `ml` versus `baseline` behavior.
- High drift: validate the upstream dataset, regenerate the report with fresher inputs, and use `MODEL_VARIANT=baseline` if service quality degrades.
