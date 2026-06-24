"""
orchestrator.py — Wires together the SOMARQD pipeline.

Steps:
  1. scraper.download()      → downloads the PDF, returns metadata
  2. Check processed.json    → skip if already processed (unless FORCE_REPROCESS)
  3. extractor.extract()     → extracts data from the PDF
  4. file_generator.generate_files() → writes DATA, META, ZIP to output/
"""

import json
import logging
import os
import sys

import config
from scraper import download
from extractor import extract
from file_generator import generate_files

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Processed-data cache
# ══════════════════════════════════════════════════════════════════════════════

def _load_processed():
    """Return set of already-processed keys like '2026-Q2_20260504'."""
    if not os.path.exists(config.PROCESSED_LOG):
        return set()
    try:
        with open(config.PROCESSED_LOG, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return set(data.get('processed', []))
    except Exception:
        return set()


def _mark_processed(key):
    """Persist a new processed key."""
    processed = _load_processed()
    processed.add(key)
    with open(config.PROCESSED_LOG, 'w', encoding='utf-8') as f:
        json.dump({'processed': sorted(processed)}, f, indent=2)


def _make_process_key(year, quarter, date_str):
    return f"{year}-Q{quarter}_{date_str}"


# ══════════════════════════════════════════════════════════════════════════════
# Main pipeline
# ══════════════════════════════════════════════════════════════════════════════

def main():
    """Run the full SOMARQD pipeline. Returns 0 on success, 1 on failure."""
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    try:
        logger.info("=== SOMARQD pipeline started ===")

        # ── Step 1: Download ──────────────────────────────────────────────────
        logger.info("Step 1: Scraping — finding and downloading the PDF...")
        download_result = download()

        year         = download_result['year']
        quarter      = download_result['quarter']
        date_str     = download_result['date_str']
        pdf_path     = download_result['pdf_path']
        period_label = download_result['period_label']

        logger.info(
            f"Downloaded: {year} Q{quarter} | Date: {date_str} | "
            f"Period: {period_label} | PDF: {pdf_path}"
        )

        # ── Step 2: Processed check ───────────────────────────────────────────
        process_key = _make_process_key(year, quarter, date_str)
        if not config.FORCE_REPROCESS and process_key in _load_processed():
            logger.info(
                f"Already processed: {process_key}. "
                "Set FORCE_REPROCESS=True in config.py to re-run."
            )
            return 0

        # ── Step 3: Extract ───────────────────────────────────────────────────
        logger.info("Step 3: Extracting data from PDF...")
        extraction_result = extract(pdf_path, year, quarter, period_label, date_str)

        logger.info(f"Extraction complete:")
        for code, val in extraction_result['data'].items():
            logger.info(f"  {code}: {val}")

        # ── Step 4: Generate output files ─────────────────────────────────────
        logger.info("Step 4: Writing output files...")
        paths = generate_files(extraction_result)

        logger.info(f"Data file  -> {paths['data_path']}")
        logger.info(f"Meta file  -> {paths['meta_path']}")
        logger.info(f"ZIP file   -> {paths['zip_path']}")

        # ── Step 5: Mark as processed ─────────────────────────────────────────
        _mark_processed(process_key)
        logger.info(f"Marked as processed: {process_key}")

        logger.info("=== SOMARQD pipeline completed successfully ===")
        return 0

    except Exception as e:
        logger.exception(f"Pipeline failed: {e}")
        return 1
