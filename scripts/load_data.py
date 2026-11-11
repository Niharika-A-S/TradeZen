"""CLI script for inspecting and loading historical CSV data into PostgreSQL."""
import argparse
import logging
import sys
from pathlib import Path

from app.data.loader import (
    inspect_all_csvs,
    load_all_csvs,
    SUPPORTED_SYMBOLS,
    DEFAULT_START_DATE,
    DEFAULT_END_DATE,
)
from app.database import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="TradeZen Historical Data Loader")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Inspect CSV files and print metadata without loading into DB"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Load all available historical bars (over 10 years) instead of default 100 trading days"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=DEFAULT_START_DATE,
        help=f"Filter start date (YYYY-MM-DD), default: {DEFAULT_START_DATE}"
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=DEFAULT_END_DATE,
        help=f"Filter end date (YYYY-MM-DD), default: {DEFAULT_END_DATE}"
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Comma-separated stock symbols (default: all 5: INFY,RELIANCE,TCS,HDFCBANK,SBIN)"
    )
    parser.add_argument(
        "--dir",
        type=str,
        default=None,
        help="Custom directory path containing CSV files"
    )

    args = parser.parse_args()
    data_dir = Path(args.dir) if args.dir else None

    # Step 1: Inspection
    logger.info("Inspecting CSV files in data directory...")
    inspection_results = inspect_all_csvs(data_dir=data_dir)

    print("\n" + "=" * 90)
    print("CSV DATASET INSPECTION REPORT")
    print("=" * 90)
    for info in inspection_results:
        print(f"Symbol: {info['symbol']:<10} | File: {info['file_name']:<22} | Size: {info['file_size_mb']:>6.2f} MB")
        print(f"  Total Rows: {info['total_rows']:,} | Trading Days: {info['unique_trading_days']:,}")
        print(f"  Date Range: {info['start_date']}  to  {info['end_date']}")
        print(f"  Columns:    {info['columns']}")
        print(f"  Sample Bar: {info['sample_row']}")
        print("-" * 90)

    if args.inspect:
        print("\nInspection complete (--inspect specified, skipping database insertion).")
        return

    # Step 2: Database loading
    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else SUPPORTED_SYMBOLS

    print("\nLoading data into PostgreSQL database...")
    summary = load_all_csvs(
        data_dir=data_dir,
        symbols=symbols,
        start_date=args.start_date if not args.full else None,
        end_date=args.end_date if not args.full else None,
        full=args.full,
        engine=engine
    )

    print("\n" + "=" * 50)
    print("DATA LOADING SUMMARY")
    print("=" * 50)
    total = 0
    for sym, count in summary.items():
        print(f"  {sym:<12}: {count:>8,} bars loaded")
        total += count
    print("-" * 50)
    print(f"  TOTAL       : {total:>8,} bars loaded")
    print("=" * 50)


if __name__ == "__main__":
    main()
