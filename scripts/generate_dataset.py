"""Generate bot behavior dataset script for TradeZen (Step 4 & Prompt A).

Simulates 30 programmed bot traders across historical trading days and 5 personalities,
constructs relative behavioral features for each 30-minute window, and produces
data/behavior_dataset.csv for XGBoost training and baseline evaluation.
"""
import os
import sys
import time
from pathlib import Path
import pandas as pd

from app.database import SessionLocal
from app.simulator.engine import SimulationEngine
from app.simulator.bot import create_default_bots, BotPersonality


def generate_behavior_dataset(output_path: str = "data/behavior_dataset.csv", random_seed: int = 42) -> pd.DataFrame:
    """Runs the 30-bot simulation and generates the behavior dataset CSV."""
    print("=" * 60)
    print("TradeZen Prompt A: Bot Trader Simulation & Dataset Generation")
    print("=" * 60)

    start_time = time.time()
    db = SessionLocal()
    try:
        engine = SimulationEngine(session=db)
        print("1. Loading historical price bars from database...")
        engine.load_market_data()
        num_dates = len(engine.dates)
        num_symbols = len(engine.symbols)
        print(f"   Loaded {num_dates} trading days across {num_symbols} symbols.")

        bots = create_default_bots(seed=random_seed)
        num_bots = len(bots)
        print(f"2. Initialized {num_bots} programmed bots across 5 personalities (6 bots each).")
        for p in BotPersonality:
            p_bots = [b for b in bots if b.personality == p]
            print(f"   - {p.value:18s}: {len(p_bots)} bots ({p_bots[0].name} to {p_bots[-1].name})")

        # Theoretical maximum rows = num_bots * num_dates * 12 windows
        expected_rows = num_bots * num_dates * 12
        print(f"   Expected maximum rows ({num_bots} bots * {num_dates} days * 12 windows): {expected_rows:,}")

        print("3. Running simulation loop across all trading days and windows...")
        sim_start = time.time()
        df = engine.run_simulation(bots=bots, random_seed=random_seed)
        sim_duration = time.time() - sim_start
        actual_rows = len(df)
        print(f"   Simulation completed in {sim_duration:.2f} seconds.")
        print(f"   Actual rows generated: {actual_rows:,}")
        if actual_rows != expected_rows:
            diff = expected_rows - actual_rows
            print(f"   Note: Row count difference of {diff:,} rows from theoretical maximum is due to days with insufficient intraday bar coverage (< 360 minutes).")

        # Ensure output directory exists
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

        print(f"4. Saving dataset to {output_path}...")
        df.to_csv(output_path, index=False)
        total_duration = time.time() - start_time
        print(f"   Successfully wrote {actual_rows:,} rows to {output_path} ({total_duration:.2f}s total).")

        # Report Metrics
        print("\n" + "=" * 60)
        print("DATASET METRICS & VALIDATION REPORT")
        print("=" * 60)
        print(f"Row count: {actual_rows:,}")

        label_counts = df['label'].value_counts()
        label_pcts = df['label'].value_counts(normalize=True) * 100.0
        print("\nLabel Balance:")
        for lbl in [0, 1]:
            count = label_counts.get(lbl, 0)
            pct = label_pcts.get(lbl, 0.0)
            status_desc = "No Violation" if lbl == 0 else "Violation Alert"
            print(f"  Label {lbl} ({status_desc:15s}): {count:6,} rows ({pct:5.2f}%)")

        v_rates = df.groupby('personality')['label'].mean() * 100.0
        print("\nViolation Rates by Personality:")
        for p in BotPersonality:
            rate = v_rates.get(p.value, 0.0)
            print(f"  - {p.value:18s}: {rate:5.2f}%")

        disc_rate = v_rates.get(BotPersonality.DISCIPLINED.value, 0.0)
        ot_rate = v_rates.get(BotPersonality.OVERTRADER.value, 0.0)
        rev_rate = v_rates.get(BotPersonality.REVENGE_TRADER.value, 0.0)
        sl_rate = v_rates.get(BotPersonality.STOP_LOSS_IGNORER.value, 0.0)
        fomo_rate = v_rates.get(BotPersonality.FOMO_CHASER.value, 0.0)

        # Validation assertions
        assert actual_rows >= 25000, f"Row count {actual_rows} is less than 25,000!"
        assert ot_rate > disc_rate + 10.0, f"Overtrader ({ot_rate:.2f}%) not higher than Disciplined ({disc_rate:.2f}%)!"
        assert rev_rate > disc_rate + 10.0, f"RevengeTrader ({rev_rate:.2f}%) not higher than Disciplined ({disc_rate:.2f}%)!"
        assert sl_rate > disc_rate + 10.0, f"StopLossIgnorer ({sl_rate:.2f}%) not higher than Disciplined ({disc_rate:.2f}%)!"
        print("\nVerification Check: PASSED")
        print(f"  Clear behavioral contrast observed across personalities against Disciplined baseline ({disc_rate:.2f}%).")
        print("=" * 60)

        return df
    finally:
        db.close()


if __name__ == "__main__":
    generate_behavior_dataset()
