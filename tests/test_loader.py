"""Tests for CSV data inspection and loading."""
from pathlib import Path
import pytest

from app.data.loader import (
    inspect_all_csvs,
    inspect_csv_file,
    resolve_data_directory,
    find_csv_file,
    SUPPORTED_SYMBOLS,
    EXPECTED_COLUMNS
)


def test_data_directory_resolution():
    """Verifies that the data directory with 5 stock CSVs is found."""
    data_dir = resolve_data_directory()
    assert data_dir.exists()
    assert data_dir.is_dir()


def test_find_all_5_csv_files():
    """Verifies that all 5 required stocks exist in the data folder."""
    data_dir = resolve_data_directory()
    for symbol in SUPPORTED_SYMBOLS:
        csv_file = find_csv_file(symbol, data_dir)
        assert csv_file.exists(), f"Missing CSV for {symbol}"


def test_inspect_csv_files():
    """Verifies inspect_all_csvs validates columns, date formats, and row counts."""
    reports = inspect_all_csvs()
    assert len(reports) == 5

    symbols_found = set()
    for rep in reports:
        symbols_found.add(rep["symbol"])
        assert rep["columns"] == EXPECTED_COLUMNS
        assert rep["total_rows"] > 1_000_000
        assert rep["unique_trading_days"] > 2_000
        assert "2015-02-02" in rep["start_date"]
        assert "2026" in rep["end_date"]

    assert symbols_found == set(SUPPORTED_SYMBOLS)
