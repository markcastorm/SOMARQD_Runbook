# SOMARQD Runbook Developer Documentation

This document describes the design, execution commands, codebase structure, and key findings of the US Treasury Quarterly Refunding Estimates pipeline.

## Execution & Test Commands

- **Run Full Pipeline**:
  ```bash
  python main.py
  ```
  Runs the end-to-end flow: scrapes latest files, checks for new releases, extracts data, and generates output files.

- **Run Extractor Tests**:
  ```bash
  python test_extraction.py
  ```
  Tests the extraction logic on all sample PDFs inside the `Project_information/samplepdfs/` directory.

---

## Codebase Architecture

The project follows a standard SIMBA pipeline structure:

1. **[config.py](file:///D:/Projects/SIMBA-RUNBOOKS/SOMARQD_Runbook/config.py)**: Configures download/output directories, target year/quarter selection (uses auto-detect if `None`), output column mapping (codes, descriptions, and Excel structure), and static metadata fields.
2. **[scraper.py](file:///D:/Projects/SIMBA-RUNBOOKS/SOMARQD_Runbook/scraper.py)**: Scrapes the US Treasury archive. Tries direct requests first and falls back to Selenium stealth.
   - Core function: `download()` -> downloads the target PDF.
   - Correctly extracts page publication date avoiding sidebar elements.
3. **[extractor.py](file:///D:/Projects/SIMBA-RUNBOOKS/SOMARQD_Runbook/extractor.py)**: Reads the PDF using PyMuPDF (`fitz`), groups words by horizontal position, finds column centers from the indices row `(1)` to `(7)`, parses data blocks per quarter period, and extracts estimated values.
   - Core function: `extract()` -> extracts the 7 values.
4. **[file_generator.py](file:///D:/Projects/SIMBA-RUNBOOKS/SOMARQD_Runbook/file_generator.py)**: Saves output files (DATA, META, ZIP) containing exactly 2 data rows representing the current release quarter and the next quarter. No historical master file is maintained.
   - Core function: `generate_files(result)` -> returns generated file paths.
5. **[orchestrator.py](file:///D:/Projects/SIMBA-RUNBOOKS/SOMARQD_Runbook/orchestrator.py)**: Wires together download, processed-check (tracks `processed.json`), extraction, and output generation.
   - Core function: `main()`.
6. **[main.py](file:///D:/Projects/SIMBA-RUNBOOKS/SOMARQD_Runbook/main.py)**: Entry point.

---

## Key Solutions & Findings

### 1. Two-Row Output Design (Non-Incremental)
As requested, the generated DATA xlsx file does not merge with any historical master file. It contains exactly two data rows representing the estimates of the current release:
- **Current Quarter (Quarter of Release)**: e.g. `2026-Q1` with `QRELEASE` values filled and `QNEXT` values as blank.
- **Next Quarter**: e.g. `2026-Q2` with `QNEXT` values filled and `QRELEASE` values as blank.

### 2. Robust Block Year Extraction (Split-based)
When parsing tables in historical or Q1 PDFs (e.g. `2026 Q1`), we found that the announcement dates (like `November 3, 2025` for the `Jan - Mar 2026` block) were grouped into the same row as the quarter range (`Jan - Mar November 3, 2025`). In this case, `re.search` matched `2025` instead of `2026` as the block year.

To solve this, we implemented `_get_quarter_column_text()`:
- It splits the row text by the `DATE_PATTERN` or keywords like `Actual` or `Revisions` and only looks for the block year in the left-hand portion of the text (representing the `Quarter` column).
- This approach is entirely layout-independent, meaning shifts in margins or coordinates (like in May 2026 where column `Quarter` moved to `x0 = 85.44`) do not break parsing.

### 3. Robust Page Date Extraction
The press release pages contain multiple `<time>` elements (such as sidebar lists with class `.mm-news-row`).
We updated `_extract_page_date()` in [scraper.py](file:///D:/Projects/SIMBA-RUNBOOKS/SOMARQD_Runbook/scraper.py) to target the specific container class `.field--name-field-news-publication-date` which holds the actual publication date (e.g. `2026-05-04`), preventing incorrect cache checks.

### 4. Change in Cash Balance Value Difference
In `Sources-Uses-Table-May2026.pdf` (for `2026-Q2` release):
- Marketable Borrowing = `189.0`
- End of Quarter Cash Balance = `900.0`
- Change in Cash Balance = `7.0` (latest estimate on row May 4, 2026)
- SOMA Redemptions = `0.0`

*Note:* The reference CSV contained `-43.0` for Change in Cash Balance. This `-43` is the revision delta (difference between the February and May estimates), whereas the pipeline extracts the actual latest estimate (`7.0`) which is correct.

### 5. CRITICAL FIX (2026-06-24): Dynamic Column Tolerance & Merged-Row Year Bug

**Problem:** The extractor worked for 2026 PDFs but failed for older PDFs (e.g. 2025 Q4, Q3, Q2):
- `SOMARQD.CHANGEINCASHBALANCE.QNEXT.Q` returned `None` instead of `0.0`
- `SOMARQD.CHANGEINCASHBALANCE.QRELEASE.Q` returned `None` for some PDFs
- For Feb 2026 (Q1), the `jan - mar` target block was `NOT FOUND`

**Root Cause 1 — Fixed COL_TOLERANCE too tight:**
The extractor used a hardcoded `COL_TOLERANCE = 18 pts` for column matching.
Different PDF vintages use different page widths (compact ~560pt vs wide ~700pt),
causing `0` values and some numeric values to render at x-offsets of 19.9–25.5 pts
from their column center — just outside the 18 pt window.

**Root Cause 2 — Formula row skews min_gap:**
The header row contains `(4) = (2) + (3)` which places cols 3 and 4 close together
(min gap ≈29-46 pts). Using `min_gap × 0.40` as tolerance was too small.

**Fix — Dynamic tolerance based on MEDIAN column gap:**
```python
def _compute_col_tolerance(col_centers):
    xs = sorted(col_centers.values())
    gaps = [xs[i+1] - xs[i] for i in range(len(xs)-1)]
    median_gap = statistics.median(gaps)   # unaffected by formula col compression
    tol = min(median_gap * 0.45, 35.0)    # 45% of median, max 35 pts
    tol = max(tol, 12.0)                  # never below 12 pts
    return tol
```
Typical effective tolerances: 21-33 pts depending on PDF layout.

**Root Cause 3 — Merged-row year detection bug (Feb 2026 Q1 PDF):**
In the Feb 2026 PDF, the `Jan - Mar` period row was merged with the November 3 estimate:
`Jan - Mar  November 3, 2025  511  578  (67)  511  0  850  0`
The code incorrectly set `block['year'] = 2025` from the announcement date.
The actual year `2026` was on the NEXT row: `2026  February 2, 2026  530...`

**Fix:** Removed year-from-date logic from merged-row detection.
Year is ONLY set from the quarter-column text portion (before the date),
OR from a standalone year-number row that follows the period label row.

**Root Cause 4 — Merged period+data rows (Jul 2025 style):**
July 2025 PDF packs the period label AND first estimate AND values all on one row:
`Jul - Sep  April 28, 2025  480  554  (75)  480  0  850  (15)`
The previous parser skipped the data values on period-label rows entirely.

**Fix:** Added merged-row detection: if a period-label row also contains numeric
column values (via `_classify_row()`), the entry is captured and appended to
the new block's entries.

**Test Results After Fix — ALL 5 PDFs PASS (35/35 fields):**
| PDF | SOMA | MB.QREL | MB.QNXT | CCB.QREL | CCB.QNXT | EOQ.QREL | EOQ.QNXT |
|-----|------|---------|---------|----------|----------|----------|----------|
| May 2026 Q2 | 0 | 189 | 671 | 7 | 50 | 900 | 950 |
| Feb 2026 Q1 | 0 | 574 | 109 | -23 | 50 | 850 | 900 |
| Nov 2025 Q4 | -10 | 569 | 578 | -41 | **0** | 850 | 850 |
| Jul 2025 Q3 | -15 | 1007 | 590 | 393 | **0** | 850 | 850 |
| Apr 2025 Q2 | -15 | 514 | 554 | 444 | **0** | 850 | 850 |

The bolded **0** values were previously extracted as `None`.

**Test scripts:**
- `test_extraction.py` — original test with reference comparison for May 2026
- `test_all_pdfs_to_csv.py` — comprehensive test of ALL 5 sample PDFs with full reference expected values and CSV output to `Project_information/extraction_test_results.csv`
