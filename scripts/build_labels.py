import argparse
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--infile", type=str, default="data/processed/features_replay.parquet")
    parser.add_argument("--outfile", type=str, default="data/processed/features_labeled.parquet")
    parser.add_argument("--horizon_seconds", type=int, default=60)
    parser.add_argument("--tau_quantile", type=float, default=0.95)
    args = parser.parse_args()

    print("Loading features...")
    df = pd.read_parquet(args.infile).copy()

    # Convert and sort by time
    df["exchange_time"] = pd.to_datetime(df["exchange_time"], utc=True)
    df = df.sort_values("exchange_time").reset_index(drop=True)

    # Ensure numeric returns
    df["log_return"] = pd.to_numeric(df["log_return"], errors="coerce")

    print("Computing future volatility...")

    times = df["exchange_time"]
    rets = df["log_return"]

    future_sigma = []
    n = len(df)

    for i in range(n):
        t0 = times.iloc[i]
        t1 = t0 + pd.Timedelta(seconds=args.horizon_seconds)

        # future window
        mask = (times > t0) & (times <= t1)
        window = rets[mask].dropna()

        if len(window) >= 2:
            future_sigma.append(window.std())
        else:
            future_sigma.append(pd.NA)

        if i % 1000 == 0:
            print(f"Processed {i}/{n}")

    df["sigma_future_60s"] = future_sigma

    print("Computing threshold tau...")

    valid_sigma = pd.to_numeric(df["sigma_future_60s"], errors="coerce").dropna()
    tau = valid_sigma.quantile(args.tau_quantile)

    print(f"Tau (quantile {args.tau_quantile}): {tau}")

    print("Creating labels...")

    df["label_spike"] = (
        pd.to_numeric(df["sigma_future_60s"], errors="coerce") >= tau
    ).astype("Int64")

    # Save output
    df.to_parquet(args.outfile, index=False)

    print("\nSaved labeled dataset.")
    print(f"Output file: {args.outfile}")
    print(f"Total rows: {len(df)}")
    print(f"Valid sigma rows: {len(valid_sigma)}")

    print("\nLabel distribution:")
    print(df["label_spike"].value_counts(dropna=False))

    print("\nSample:")
    print(df[["exchange_time", "log_return", "sigma_future_60s", "label_spike"]].head(10))


if __name__ == "__main__":
    main()