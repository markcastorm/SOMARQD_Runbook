# SOMARQD Runbook Developer Documentation

This document describes the execution commands, codebase architecture, implementation details, and functional specifications of the US Treasury Quarterly Refunding Estimates pipeline.

---

## Execution & Test Commands

- **Run Full Pipeline**:
  ```bash
  python main.py
  ```
  Runs the end-to-end flow: scrapes latest files (Selenium stealth primary, requests backup), checks for new releases, extracts data, and generates output files.

- **Run Extractor Tests**:
  ```bash
  python test_extraction.py
  ```
  Tests the extraction logic on all sample PDFs inside the `Project_information/samplepdfs/` directory.

- **Run Standalone Scraper Test**:
  ```bash
  python test_scraper_selenium.py
  ```
  Runs only the scraper flow in the Selenium stealth single-session mode to test browser initialization and native PDF downloading.

- **Run Comprehensive Regression Suite**:
  ```bash
  python Project_information/test_all_pdfs_to_csv.py
  ```
  Extracts data from all 5 sample PDFs, compares results against manual reference values, and outputs a CSV log.

---

## Codebase Architecture & Function Reference

The codebase consists of five main modules: `config.py`, `scraper.py`, `extractor.py`, `file_generator.py`, and `orchestrator.py`, tied together by `main.py`.

### 1. config.py (Configuration Schema)
Defines environment variables, output mappings, and target periods. It contains no functions. Key configurations:
* `COLUMNS`: Dict list defining the absolute code column order, descriptions, mapping positions, and row target types (e.g. `QRELEASE` vs `QNEXT`).
* `META_STATIC`: Static schema keys populated in the metadata output sheets.

---

### 2. scraper.py (Scraping and File Download)
Handles page navigation, target quarter resolution, native browser click tracking, and legacy PDF wrapper redirections.

#### `_get_chrome_version()`
* **Purpose**: Detects the installed Google Chrome browser major version to align chromedriver versions and prevent startup crashes.
* **Logic**: On Windows, reads `winreg` keys under `HKCU` or `HKLM` (specifically `Software\Google\Chrome\BLBeacon\version`). On Linux, executes shell commands (`google-chrome --version` etc.) and parses the stdout string.

#### `_make_run_dir(year, quarter)`
* **Purpose**: Creates a timestamped local download subfolder for target PDFs.
* **Returns**: Absolute path string `downloads/<timestamp>/<year>/Q<quarter>/`.

#### `_parse_archive_html(html)`
* **Purpose**: Parses the HTML of the main archives page to build a structured database of active releases.
* **Logic**: Uses `BeautifulSoup` to scan the grid table. Locates rows with year ID headers (`<th id="YYYY">`) followed by quarter headers (`<th headers="YYYY">`). Extracts `href` links for cells that contain active `<a>` tags.
* **Returns**: Dict mapping `year (int) -> { quarter_num (int): url_or_None }`.

#### `_get_targets(available)`
* **Purpose**: Resolves the list of targets to process based on user configurations.
* **Logic**: 
  * If `TARGET_YEAR` and `TARGET_QUARTER` are `None`: Finds the single newest year and quarter containing a clickable link (Auto-detect mode).
  * If `TARGET_YEAR` is set but `TARGET_QUARTER` is `None`: Returns a chronological list of **all active quarters** for that year (Multi-Quarter Loop).
  * If both are specified: Returns a list containing that single target.
* **Returns**: List of `(year, quarter, url)` tuples.

#### `_extract_page_date(html)`
* **Purpose**: Parses the publication date of the press release.
* **Logic**: Searches for a `<time datetime="...">` tag specifically inside the news container `.field--name-field-news-publication-date` (avoiding sidebar news feeds). Falls back to general regex date matching (e.g., `May 4, 2026`).
* **Returns**: Date string in `YYYYMMDD` format.

#### `_find_sources_uses_link(html, page_url)`
* **Purpose**: Locates the "Sources and Uses Table" PDF link on the press-release page.
* **Logic**: Searches tags `<a>` for keyword fragments (`sources and uses table`, `here`, etc.) or for href values containing `sources` and `uses` ending in `.pdf`.

#### `_wait_for_download(download_dir, timeout=45)`
* **Purpose**: Polls a download directory until a native Chrome PDF download finishes writing.
* **Logic**: Iterates over directory contents. Finds files ending in `.pdf` (excluding temporary `.crdownload` or `.tmp` extensions). Verifies that the file size has stabilized (remains identical after a 1.5-second sleep).
* **Returns**: Absolute path to the downloaded PDF file.

#### `_requests_session()`
* **Purpose**: Creates a pre-configured `requests.Session` populated with real-browser user agent headers.

#### `_download_pdf_via_requests(url, dest_path, cookies=None)`
* **Purpose**: Downloads a PDF directly via requests (used in backup strategies or cookie failovers).
* **Logic**: Calls `requests.get` with optional cookie parameters, checks content headers to ensure it is not an HTML error page, writes chunks, and verifies file size.

#### `_extract_link_from_wrapper_pdf(pdf_path)`
* **Purpose**: Extracts target PDF URLs embedded inside legacy wrapper PDFs.
* **Logic**: Opens the PDF via `fitz`, reads the annotations (`/Annots`) of all pages, and checks for `LINK_URI` annotations containing URL string pointers.

#### `_handle_legacy_pdf_link(pdf_url, year, quarter, session, cookies=None)`
* **Purpose**: Downloads direct PDF wrapper links (e.g. 2015 Q3) and replaces them with their embedded target PDFs.
* **Logic**: Downloads the wrapper, extracts its annotations, triggers browser download or requests download of the real table PDF, overwrites the wrapper, and returns metadata.

#### `try_direct_download(targets)`
* **Purpose**: Backup strategy to download targets directly using `requests` if Selenium fails.

#### `_build_selenium_driver()`
* **Purpose**: Boots up an undetected Chrome session with stealth options.
* **Logic**: Configures options (headless mode, GPU disables, user agent, language), sets Chrome preferences to force PDFs to open externally (triggering download), starts `uc.Chrome(...)` passing `version_main`, and applies `selenium_stealth` patches.

#### `download()`
* **Purpose**: Primary orchestrator for the download phase.
* **Logic**:
  1. Boots a **single browser session** using `_build_selenium_driver()`.
  2. Visits the archive page, extracts target items, and loops through them.
  3. Updates the browser's download directory via CDP (`Page.setDownloadBehavior`) for each target.
  4. Scrolls to cells and clicks natively via JS (`arguments[0].click()`).
  5. Scrolls and clicks the PDF link on the press release natively, then executes `_wait_for_download()`.
  6. Falls back to requests + cookies if native download fails, and falls back to direct requests entirely if the browser crashes or fails to initialize on startup.

---

### 3. extractor.py (Data Extraction Engine)
Reads the downloaded PDF, parses the structured grid coordinates, maps columns, and extracts values.

#### `_clean_number(raw)`
* **Purpose**: Standardizes PDF text cells into floats (e.g. `(45)` -> `-45.0`, `1,250` -> `1250.0`).

#### `_get_words(page)`
* **Purpose**: Parses PyMuPDF `words` layouts. Returns list of `(x0, y0, text)` items.

#### `_group_into_rows(words, row_gap=3.5)`
* **Purpose**: Groups text blocks into horizontal table rows.
* **Logic**: Sorts word tokens by y-coordinate. Groups tokens whose y-coordinates are within `row_gap` points of each other.

#### `_find_column_centers(rows)`
* **Purpose**: Detects the absolute x-coordinates of table columns dynamically.
* **Logic**: Scans rows to find the index row `(1) (2) (3) ... (7)`. Captures the first occurrences of these values to define column centers, falling back to empirical defaults if not found.

#### `_compute_col_tolerance(col_centers)`
* **Purpose**: Computes layout-adaptive tolerances for column coordinates.
* **Logic**: Computes adjacent column gaps. Calculates `median_adjacent_gap * 0.45` (floored at 12pts and capped at 35pts).

#### `_get_col_value(row, col_centers, col_num, tol)`
* **Purpose**: Fetches the numerical value belonging to column `col_num` from a row.
* **Logic**: Loops through row tokens, calculates distance to column center, and selects the closest token within tolerance `tol`.

#### `_get_quarter_column_text(text)`
* **Purpose**: Isolates the quarter label portion of a row, removing dates or Actual flags.
* **Logic**: Splits the row text using the `DATE_PATTERN` or keywords like `Actual`/`Revisions` to prevent parsing merged year tags incorrectly.

#### `_classify_row(text, vals)`
* **Purpose**: Classifies a row into an estimate category (e.g., `AnnDate`, `Actual`, `Revisions`).

#### `_parse_pdf_table(rows, col_centers, tol)`
* **Purpose**: Parses rows into chronological year-quarter blocks.
* **Logic**: Uses a state-machine that registers period changes (e.g. `Apr - Jun`), captures block years, parses merged lines (e.g., Jul 2025 where period and values are single-row), and collects entries.

#### `_pick_estimate_row(block, is_quarter_of_release)`
* **Purpose**: Selects the target row in a block. Picks the latest `AnnDate` (highest date string) or falls back to `Actual`.

#### `extract(pdf_path, year, quarter, period_label, date_str)`
* **Purpose**: Runs the full extraction sequence, resolving target and next-quarter data blocks and returning a mapped dict of the 7 target keys.

---

### 4. file_generator.py (File Writer)
Generates the XLSX database worksheets, metadata sheets, ZIP compression bundles, and executes run folder cleanup.

#### `_write_data(data_dict, date_str, run_dir)`
* **Purpose**: Writes the DATA Excel sheet.
* **Logic**: Populates code headers in row 0, descriptions in row 1, and inserts sorted Release Quarter and Next Quarter rows.

#### `_write_meta(date_str, run_dir)`
* **Purpose**: Writes the META Excel sheet schema.

#### `_write_zip(date_str, run_dir, files)`
* **Purpose**: Bundles generated Excel files into a zip archive.

#### `_cleanup_old_runs(keep=10)`
* **Purpose**: Keeps only the 10 most recent historic folders under `output/`.

#### `generate_files(extraction_result, run_dir=None)`
* **Purpose**: Maps results into the two release-estimates rows, saves output files, copies them to the `latest/` directory, and performs cleanups.

---

### 5. orchestrator.py (Pipeline Execution Core)
Coordinates database state caches, schedules download targets, and triggers extraction loops.

#### `_load_processed()`
* **Purpose**: Reads `processed.json` to load the database of already completed releases.

#### `_mark_processed(key)`
* **Purpose**: Appends a completed run key (`{year}-Q{quarter}_{date_str}`) to `processed.json`.

#### `main()`
* **Purpose**: End-to-end pipeline manager. Runs the scraper, filters out previously completed targets, clears `latest/` once, loops through new targets to extract data, writes outputs, and logs cache entries.
