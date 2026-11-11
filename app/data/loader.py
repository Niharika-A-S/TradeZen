"""Historical CSV data loader for TradeZen.

Reads 1-minute OHLCV CSVs from the data directory, validates schemas,
and loads them into PostgreSQL / SQLite with high performance.
"""
import io
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import settings
from app.database import engine as default_engine

logger = logging.getLogger(__name__)

EXPECTED_COLUMNS = ["date", "open", "high", "low", "close", "volume"]
SUPPORTED_SYMBOLS = ["INFY", "RELIANCE", "TCS", "HDFCBANK", "SBIN"]

# Default 100 trading days window centered around target date 2022-03-10
DEFAULT_START_DATE = "2021-12-28"
DEFAULT_END_DATE = "2022-05-25"


def resolve_data_directory(data_dir: Optional[Path] = None) -> Path:
    """Finds the data directory (checks Data/ and data/)."""
    if data_dir is not None:
        p = Path(data_dir)
        if p.exists():
            return p

    candidates = [
        settings.data_path,
        Path("Data"),
        Path("data"),
        Path(__file__).resolve().parent.parent.parent / "Data",
        Path(__file__).resolve().parent.parent.parent / "data",
    ]
    for c in candidates:
        if c.exists() and c.is_dir():
            return c

    raise FileNotFoundError(f"Could not locate data directory containing stock CSVs. Checked: {[str(c) for c in candidates]}")


def find_csv_file(symbol: str, data_dir: Path) -> Path:
    """Finds CSV file for a symbol regardless of casing."""
    candidates = [
        data_dir / f"{symbol}_minute.csv",
        data_dir / f"{symbol.upper()}_minute.csv",
        data_dir / f"{symbol.lower()}_minute.csv",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(f"CSV file for {symbol} not found in {data_dir}")


def inspect_csv_file(file_path: Path) -> Dict[str, Any]:
    """Inspects a single CSV file, returning metadata, date range, and structure."""
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Read head and tail
    head_df = pd.read_csv(file_path, nrows=5)
    cols = list(head_df.columns)

    # Check columns
    missing_cols = [c for c in EXPECTED_COLUMNS if c not in cols]
    if missing_cols:
        raise ValueError(f"{file_path.name} missing expected columns: {missing_cols}")

    # Read sample to verify date parsing
    sample_date_str = str(head_df["date"].iloc[0])
    try:
        sample_dt = pd.to_datetime(sample_date_str)
    except Exception as e:
        raise ValueError(f"Unable to parse date '{sample_date_str}' in {file_path.name}: {e}")

    # Estimate total rows and read first and last lines
    with open(file_path, "r", encoding="utf-8") as f:
        first_line = f.readline().strip()
        second_line = f.readline().strip()
        f.seek(0, 2)
        size_bytes = f.tell()

    # Read full date column to get true trading days count and exact range
    date_col = pd.read_csv(file_path, usecols=["date"])
    total_rows = len(date_col)
    first_date = date_col["date"].iloc[0]
    last_date = date_col["date"].iloc[-1]
    unique_days = pd.to_datetime(date_col["date"]).dt.date.nunique()

    return {
        "file_name": file_path.name,
        "columns": cols,
        "total_rows": total_rows,
        "unique_trading_days": unique_days,
        "start_date": first_date,
        "end_date": last_date,
        "file_size_mb": round(size_bytes / (1024 * 1024), 2),
        "sample_row": head_df.iloc[0].to_dict(),
    }


def inspect_all_csvs(data_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Inspects all 5 target stock CSV files in the data directory."""
    resolved_dir = resolve_data_directory(data_dir)
    results = []
    for symbol in SUPPORTED_SYMBOLS:
        file_path = find_csv_file(symbol, resolved_dir)
        info = inspect_csv_file(file_path)
        info["symbol"] = symbol
        results.append(info)
    return results


def load_single_csv(
    symbol: str,
    file_path: Path,
    engine: Engine,
    start_date: Optional[str] = DEFAULT_START_DATE,
    end_date: Optional[str] = DEFAULT_END_DATE,
    full: bool = False
) -> int:
    """Loads a single CSV file into the price_bars table."""
    logger.info("Reading %s from %s...", symbol, file_path.name)
    df = pd.read_csv(file_path)
    df["date"] = pd.to_datetime(df["date"])

    if not full and (start_date or end_date):
        if start_date:
            df = df[df["date"] >= pd.to_datetime(start_date)]
        if end_date:
            # Include entire end_date day up to 23:59:59
            end_dt = pd.to_datetime(end_date)
            if end_dt.hour == 0 and end_dt.minute == 0:
                end_dt = end_dt.replace(hour=23, minute=59, second=59)
            df = df[df["date"] <= end_dt]

    if df.empty:
        logger.warning("No rows matched criteria for %s", symbol)
        return 0

    df["symbol"] = symbol
    df = df.rename(columns={"date": "timestamp"})
    columns_to_load = ["symbol", "timestamp", "open", "high", "low", "close", "volume"]
    df = df[columns_to_load]

    is_postgres = "postgresql" in engine.dialect.name.lower()

    if is_postgres:
        # Fast bulk COPY via PostgreSQL raw connection
        raw_conn = engine.raw_connection()
        try:
            with raw_conn.cursor() as cur:
                # Create a temp staging table to handle ON CONFLICT seamlessly
                cur.execute("""
                    CREATE TEMP TABLE temp_stage_price_bars (
                        symbol VARCHAR(20),
                        timestamp TIMESTAMP WITHOUT TIME ZONE,
                        open DOUBLE PRECISION,
                        high DOUBLE PRECISION,
                        low DOUBLE PRECISION,
                        close DOUBLE PRECISION,
                        volume BIGINT
                    ) ON COMMIT DROP;
                """)

                buf = io.StringIO()
                df.to_csv(buf, index=False, header=False)
                buf.seek(0)

                cur.copy_expert(
                    "COPY temp_stage_price_bars (symbol, timestamp, open, high, low, close, volume) FROM STDIN WITH CSV",
                    buf
                )

                # Insert from staging into target table ignoring duplicates
                cur.execute("""
                    INSERT INTO price_bars (symbol, timestamp, open, high, low, close, volume)
                    SELECT symbol, timestamp, open, high, low, close, volume
                    FROM temp_stage_price_bars
                    ON CONFLICT (symbol, timestamp) DO UPDATE
                    SET open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume;
                """)
            raw_conn.commit()
        finally:
            raw_conn.close()
    else:
        # Generic fallback (e.g. SQLite for unit tests)
        with engine.begin() as conn:
            # Delete overlapping rows to avoid conflict
            min_ts = df["timestamp"].min()
            max_ts = df["timestamp"].max()
            conn.execute(
                text("DELETE FROM price_bars WHERE symbol = :s AND timestamp BETWEEN :min_ts AND :max_ts"),
                {"s": symbol, "min_ts": min_ts, "max_ts": max_ts}
            )
            df.to_sql("price_bars", con=conn, if_exists="append", index=False, chunksize=5000)

    row_count = len(df)
    logger.info("Successfully loaded %d bars for %s.", row_count, symbol)
    return row_count


def load_all_csvs(
    data_dir: Optional[Path] = None,
    symbols: Optional[List[str]] = None,
    start_date: Optional[str] = DEFAULT_START_DATE,
    end_date: Optional[str] = DEFAULT_END_DATE,
    full: bool = False,
    engine: Optional[Engine] = None
) -> Dict[str, int]:
    """Loads all specified stock CSVs into the database."""
    resolved_dir = resolve_data_directory(data_dir)
    target_symbols = symbols or SUPPORTED_SYMBOLS
    target_engine = engine or default_engine

    summary = {}
    total_loaded = 0

    logger.info(
        "Starting data load for symbols: %s | Directory: %s | Full: %s (Start: %s, End: %s)",
        target_symbols, resolved_dir, full, start_date, end_date
    )

    for sym in target_symbols:
        file_path = find_csv_file(sym, resolved_dir)
        count = load_single_csv(
            symbol=sym,
            file_path=file_path,
            engine=target_engine,
            start_date=start_date,
            end_date=end_date,
            full=full
        )
        summary[sym] = count
        total_loaded += count

    logger.info("Data loading complete. Total bars loaded: %d across %d symbols.", total_loaded, len(summary))
    return summary
