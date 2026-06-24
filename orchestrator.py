"""
orchestrator.py — Wires together the SOMARQD pipeline.

Steps:
  1. scraper.download()      → downloads the PDFs, returns list of metadata
  2. Filter out already-processed quarters based on processed.json
  3. Loop through to-process quarters:
     - extractor.extract()     → extracts data from the PDF
     - file_generator.generate_files() → writes DATA, META, ZIP to output/
  4. Update processed.json
"""

import json
import logging
import os
import sys
from datetime import datetime

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
        logger.info("Step 1: Scraping — finding and downloading the PDFs...")
        download_results = download()

        if not download_results:
            logger.info("No downloads were processed or found.")
            return 0

        # Filter down to only targets that need processing (unless config.FORCE_REPROCESS is True)
        to_process = []
        for dl in download_results:
            year     = dl['year']
            quarter  = dl['quarter']
            date_str = dl['date_str']
            process_key = _make_process_key(year, quarter, date_str)
            if not config.FORCE_REPROCESS and process_key in _load_processed():
                logger.info(f"Already processed: {process_key}. Skipping.")
            else:
                to_process.append(dl)

        if not to_process:
            logger.info("All downloaded quarters have already been processed.")
            return 0

        # Establish a single run directory for outputs of this pipeline run
        run_stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        run_dir   = os.path.join(config.OUTPUT_DIR, run_stamp)
        os.makedirs(run_dir, exist_ok=True)

        # Clear latest/ folder once
        latest_dir = os.path.join(config.OUTPUT_DIR, 'latest')
        if os.path.exists(latest_dir):
            import shutil
            shutil.rmtree(latest_dir, ignore_errors=True)
        os.makedirs(latest_dir, exist_ok=True)

        # Process each quarter in order
        for dl in to_process:
            year         = dl['year']
            quarter      = dl['quarter']
            date_str     = dl['date_str']
            pdf_path     = dl['pdf_path']
            period_label = dl['period_label']

            logger.info(f"Processing: {year} Q{quarter} | Date: {date_str} | Period: {period_label} | PDF: {pdf_path}")

            # ── Step 3: Extract ───────────────────────────────────────────────────
            logger.info(f"Extracting data from PDF for {year} Q{quarter}...")
            extraction_result = extract(pdf_path, year, quarter, period_label, date_str)

            logger.info("Extraction complete:")
            for code, val in extraction_result['data'].items():
                logger.info(f"  {code}: {val}")

            # ── Step 4: Generate output files ─────────────────────────────────────
            logger.info(f"Writing output files for {year} Q{quarter}...")
            paths = generate_files(extraction_result, run_dir)

            logger.info(f"Data file  -> {paths['data_path']}")
            logger.info(f"Meta file  -> {paths['meta_path']}")
            logger.info(f"ZIP file   -> {paths['zip_path']}")

            # ── Step 5: Mark as processed ─────────────────────────────────────────
            process_key = _make_process_key(year, quarter, date_str)
            _mark_processed(process_key)
            logger.info(f"Marked as processed: {process_key}")

        logger.info("=== SOMARQD pipeline completed successfully ===")
        return 0

    except Exception as e:
        logger.exception(f"Pipeline failed: {e}")
        return 1
