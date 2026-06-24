# SOMARQD — US Treasury Quarterly Refunding Financing Estimates Pipeline

This runbook implements the automated SIMBA pipeline for scraping, downloading, extracting, and formatting the U.S. Department of the Treasury's **Quarterly Refunding Financing Estimates (Sources and Uses Reconciliation Table)**.

---

## Pipeline Overview

The pipeline executes the following sequential steps:
1. **Scraping (`scraper.py`)**: 
   * Primary Path: Boots a single Selenium stealth browser session to navigate the Treasury archive page, traverse year and quarter headers dynamically using hierarchical XPaths, trigger human-like clicks, and download the PDF natively.
   * Backup Path: Falls back to direct HTTP `requests` and `BeautifulSoup` parsing if Selenium fails or times out.
   * Special Redirects: Automatically detects if a quarter cell links directly to a PDF wrapper page (common in legacy files like 2015 Q3). It reads PDF annotations (`/Annots`) via `fitz`, extracts the real table PDF URL, and downloads it in place of the wrapper.
2. **Extraction (`extractor.py`)**:
   * Opens the downloaded Sources and Uses PDF via `fitz` (PyMuPDF).
   * Groups words by horizontal bounding boxes into rows.
   * Automatically detects the column positions from the `(1)` to `(7)` indices row and computes a layout-adaptive column tolerance (45% of the median adjacent column gap).
   * Matches estimated values to their respective columns.
   * Extracts values for the **Quarter of Release** and **Next Quarter** (Marketable Borrowing, Change in Cash Balance, End-Of-Quarter Balance, and SOMA Redemptions).
3. **File Generation (`file_generator.py`)**:
   * Generates `SOMARQD_DATA_<YYYYMMDD>.xlsx` (holding two rows: the Quarter of Release and Next Quarter estimates).
   * Generates `SOMARQD_META_<YYYYMMDD>.xlsx` (holding static meta schemas).
   * Bundles both files into `SOMARQD_<YYYYMMDD>.zip`.
   * Overwrites the latest versions under `output/latest/` and keeps up to 10 timestamped run directories under `output/`.

---

## Directory Structure

```
SOMARQD_Runbook/
├── config.py              # Configuration settings and absolute column mapping
├── scraper.py             # Single-session Selenium scraper + requests backup
├── extractor.py           # Layout-adaptive PyMuPDF table extraction engine
├── file_generator.py      # Writes Excel and ZIP outputs (timestamped + latest)
├── orchestrator.py        # Wires together scrape, extraction, and output flows
├── main.py                # Pipeline execution entry point
├── processed.json         # Cache database mapping completed releases to skip runs
├── test_scraper_selenium.py  # Standalone Selenium scraper verification test
├── Project_information/   # Documentation, screenshots, expected sheets, and tests
│   ├── CLAUDE.md          # Technical developer documentation (functions detail)
│   ├── information.txt    # Technical brief and source specifications
│   ├── samplepdfs/        # Sample PDFs (May 2026, Feb 2026, Nov 2025, Jul 2025, Apr 2025)
│   └── test_all_pdfs_to_csv.py  # Regression test runner across all 5 sample PDFs
└── output/                # Output directory (created at run-time)
    ├── latest/            # Holds outputs from the most recent successful run
    └── <timestamp>/       # Historic run folders (auto-cleaned to keep last 10)
```

---

## Prerequisites & Installation

The pipeline runs on Python 3.8+ (tested on Python 3.11). Ensure all dependencies are pre-installed in your environment:

```bash
pip install requests beautifulsoup4 pymupdf openpyxl pandas undetected-chromedriver selenium-stealth
```

---

## Execution Commands

### 1. Run the Full End-to-End Pipeline
Executes the scraper to auto-detect the latest available quarter on the Treasury site, checks if it has been processed, extracts values, and saves files.
```bash
python main.py
```

### 2. Verify Selenium Fallback Path Directly
Runs only the Selenium scraper flow (using version matching and native downloads) for the configured targets to ensure browser automation is working.
```bash
python test_scraper_selenium.py
```

### 3. Run Extractor Tests
Verifies the extraction logic on the sample PDFs inside the `Project_information/samplepdfs/` directory.
```bash
python test_extraction.py
```

### 4. Run Comprehensive Regression Suite
Extracts data from all 5 historic sample PDFs, compares results against manual reference values, outputs a pass/fail table, and writes results to `Project_information/extraction_test_results.csv`.
```bash
python Project_information/test_all_pdfs_to_csv.py
```

---

## Configuration (`config.py`)

Key parameters in `config.py` can be adjusted to control the pipeline behavior:
* `TARGET_YEAR` (`int` or `None`): Set to a year (e.g. `2025`) to restrict processing to that calendar year. Set to `None` to auto-detect the latest year with active links.
* `TARGET_QUARTER` (`int` or `None`): Set to a quarter number (`1`-`4`) to restrict processing to that specific quarter. If `TARGET_YEAR` is specified and `TARGET_QUARTER` is `None`, the scraper downloads **all available quarters** for that year in a loop.
* `FORCE_REPROCESS` (`bool`): Set to `True` to bypass the `processed.json` cache check and force the pipeline to process and generate files even if it was previously processed.
* `HEADLESS_MODE` (`bool`): Defaults to `True` for server environments. Can be set to `False` to visually debug Chrome browser navigation.
