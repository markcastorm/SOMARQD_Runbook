#!/usr/bin/env python3
"""
main.py — Entry point for the SOMARQD pipeline.

Usage:
    python main.py

The pipeline:
  1. Navigates to the US Treasury quarterly refunding archive page
  2. Finds the latest (or configured) available quarter link
  3. Downloads the Sources and Uses Table PDF
  4. Extracts Marketable Borrowing, Cash Balance, and SOMA Redemptions
  5. Writes SOMARQD_DATA_<date>.xlsx, SOMARQD_META_<date>.xlsx, SOMARQD_<date>.zip
     to output/<timestamp>/ and output/latest/
"""
import sys
from orchestrator import main

if __name__ == '__main__':
    sys.exit(main())
