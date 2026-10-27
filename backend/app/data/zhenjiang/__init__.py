"""Zhenjiang dataset package.

The CSV files in this directory are the Day 1 source of truth.
They are intentionally small and manually curated; every row carries
a source URL and a last-verified date.
"""

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
