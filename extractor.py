"""
extractor.py — Extract data from the Sources and Uses Reconciliation Table PDF.

PDF Structure (Sources and Uses Table):
  One page, one table titled "Sources and Uses Reconciliation Table"
  Columns (left → right):
    Quarter | Announcement Date | (1)Financing Need | (2)Marketable Borrowing |
    (3)All Other Sources | (4)Total | (5)Change in Cash Balance |
    (6)End-Of-Quarter Cash Balance | (7)SOMA Redemptions (Memo)

  Column x-centers (from header "(1)"..."(7)" labels):
    (1) ≈ 204   (2) ≈ 249   (3) ≈ 296   (4) ≈ 344
    (5) ≈ 396   (6) ≈ 451   (7) ≈ 505

Row structure per quarter period:
  Quarter period rows come in pairs:
    row A (y~-10): "Apr  -  Jun"
    row B (y~0):   "2026   <Announcement Date>   val1   val2   ...val7"
                   "2026   Actual                val1   val2   ...val7"
                   "       Revisions             val1   val2   ...val7"

  For "Quarter of Release" we want the row matching:
      "<target_period>" + "<year>" + "<latest announcement date>" + values
  For "Next Quarter" we want the same from the next period's block.

  Within each block:
    - There may be an old estimate row (earliest announcement date) → skip
    - Then an "Actual" row (if already occurred) → becomes "Quarter of Release" if no newer estimate
    - Then a "Revisions" row → skip
    - Then newer estimate rows → the latest (last) announcement date row = "Quarter of Release"
  For next quarter:
    - Only one announcement date row → that IS the "Next Quarter" estimate

Data we extract:
    SOMA Redemptions          → col (7), from the Quarter-of-Release row
    Marketable Borrowing      → col (2), from Quarter-of-Release row and Next-Quarter row
    Change in Cash Balance    → col (5), from both rows
    End-Of-Quarter Balance    → col (6), from both rows

Public API:
    extract(pdf_path, year, quarter, period_label, date_str) -> dict
"""

import re
import logging

import fitz  # PyMuPDF

import config

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Constants — derived from empirical PDF layout analysis
# ══════════════════════════════════════════════════════════════════════════════

# Default tolerance in PDF points for matching a value to a column centre.
# This is overridden dynamically based on detected column spacing.
# Dynamic rule: tolerance = min_col_gap * 0.40  (40% of smallest gap, capped at 35)
COL_TOLERANCE_DEFAULT = 25  # points — safe fallback
COL_TOLERANCE_RATIO   = 0.40  # fraction of min gap to use as tolerance
COL_TOLERANCE_MAX     = 35   # hard upper cap to avoid cross-column bleed

# Column labels in the header row
COL_LABEL_PATTERN = re.compile(r'^\(\d\)$')   # matches "(1)", "(2)", ... "(7)"

# Pattern for announcements dates: "February 2, 2026" / "May 4, 2026"
DATE_PATTERN = re.compile(
    r'\b(January|February|March|April|May|June|July|August|September|'
    r'October|November|December)\s+(\d{1,2}),\s+(20\d{2})\b'
)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _clean_number(raw):
    """Parse PDF number string → float or None. (XXX) = negative."""
    if raw is None:
        return None
    s = str(raw).strip().replace(',', '')
    if not s:
        return None
    m = re.match(r'^\((\d+(?:\.\d+)?)\)$', s)
    if m:
        return -float(m.group(1))
    try:
        return float(s)
    except ValueError:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Step 1: Get words with bounding boxes
# ══════════════════════════════════════════════════════════════════════════════

def _get_words(page):
    """Return [(x0, y0, text), ...] for all non-empty words on the page."""
    words = page.get_text('words')
    return [(w[0], w[1], w[4].strip()) for w in words if w[4].strip()]


# ══════════════════════════════════════════════════════════════════════════════
# Step 2: Group words into logical rows by y-coordinate
# ══════════════════════════════════════════════════════════════════════════════

def _group_into_rows(words, row_gap=3.5):
    """
    Group words into horizontal rows. Returns list of rows.
    Each row = list of (x0, text) sorted by x0.
    """
    if not words:
        return []
    words_sorted = sorted(words, key=lambda w: (w[1], w[0]))
    rows = []
    current_row = []
    current_y = None

    for x0, y0, text in words_sorted:
        if current_y is None or abs(y0 - current_y) <= row_gap:
            current_row.append((x0, text))
            current_y = y0 if current_y is None else (current_y + y0) / 2
        else:
            if current_row:
                rows.append(sorted(current_row, key=lambda w: w[0]))
            current_row = [(x0, text)]
            current_y = y0

    if current_row:
        rows.append(sorted(current_row, key=lambda w: w[0]))
    return rows


def _row_text(row):
    return ' '.join(t for _, t in row)


# ══════════════════════════════════════════════════════════════════════════════
# Step 3: Detect column centers from the index row "(1) (2) (3) ... (7)"
# ══════════════════════════════════════════════════════════════════════════════

def _find_column_centers(rows):
    """
    Scan rows to find the one that contains the standalone labels
    (1), (2), (3), (4), (5), (6), (7).
    Returns a dict: {1: x_center, 2: x_center, ..., 7: x_center}
    Strategy: find the first row that has at least 5 standalone "(N)" tokens.
    """
    for row in rows:
        # Collect (number, x0) pairs for standalone "(N)" tokens
        index_positions = {}
        for x0, text in row:
            m = re.match(r'^\((\d)\)$', text)
            if m:
                n = int(m.group(1))
                # Only keep the first occurrence of each number (standalone column indices)
                if n not in index_positions:
                    index_positions[n] = x0

        # We need exactly or approximately cols 1-7
        # But the header has formula text like "(4) = (2) + (3)" so (2) and (3) appear twice
        # Strategy: the FIRST occurrence of (1) through (7) from left to right = column centers
        if len(index_positions) >= 5:
            # Verify they are roughly evenly spaced (not formula duplicates)
            positions_sorted = sorted(index_positions.items(), key=lambda p: p[0])
            # Build the primary columns: take the 7 unique N=1..7 if available
            col_centers = {}
            for n, x0 in positions_sorted:
                if 1 <= n <= 7 and n not in col_centers:
                    col_centers[n] = x0
            if len(col_centers) >= 5:
                logger.debug(f"Column centers detected: {col_centers}")
                return col_centers

    # Fallback: use hardcoded approximate centers derived from empirical analysis
    logger.warning("Could not auto-detect column centers; using hardcoded fallback values.")
    return {
        1: 204.0,  # Financing Need
        2: 249.0,  # Marketable Borrowing
        3: 296.0,  # All Other Sources
        4: 344.0,  # Total
        5: 396.0,  # Change in Cash Balance
        6: 451.0,  # End-Of-Quarter Cash Balance
        7: 505.0,  # SOMA Redemptions
    }


def _compute_col_tolerance(col_centers):
    """
    Compute a dynamic column tolerance based on detected column centre spacing.

    Why median, not min?
    The column header row contains a formula like \"(4) = (2) + (3)\" which places
    cols 3 and 4 close together — this artificially shrinks the min gap.  The
    MEDIAN gap is far more representative of the true column spacing and gives a
    tolerance that:
      - Is large enough to catch '0' glyphs that render slightly off-centre
        (empirically up to ~55% of the true column gap)
      - Is small enough to avoid cross-column bleed

    Rule: tolerance = MEDIAN_adjacent_gap * 0.45
    Capped at COL_TOLERANCE_MAX (35 pts) and floored at 12 pts.
    """
    import statistics
    xs = sorted(col_centers.values())
    if len(xs) < 2:
        return COL_TOLERANCE_DEFAULT
    gaps = [xs[i+1] - xs[i] for i in range(len(xs)-1)]
    median_gap = statistics.median(gaps)
    tol = median_gap * 0.45
    tol = min(tol, COL_TOLERANCE_MAX)
    tol = max(tol, 12.0)   # never go below 12 pts
    logger.debug(f"Dynamic COL_TOLERANCE: {tol:.1f} (median_gap={median_gap:.1f}, gaps={[round(g,1) for g in gaps]})")
    return tol


# ══════════════════════════════════════════════════════════════════════════════
# Step 4: Extract value at specific column from a row
# ══════════════════════════════════════════════════════════════════════════════

def _get_col_value(row, col_centers, col_num, tol=None):
    """
    Find the value at column number col_num (1-7) from a data row.
    Returns cleaned float or None.
    """
    if tol is None:
        tol = COL_TOLERANCE_DEFAULT
    target_x = col_centers.get(col_num)
    if target_x is None:
        return None

    best = None
    best_dist = float('inf')
    for x0, text in row:
        dist = abs(x0 - target_x)
        if dist <= tol and dist < best_dist:
            best = text
            best_dist = dist

    return _clean_number(best)


# ══════════════════════════════════════════════════════════════════════════════
# Step 5: Parse data rows into a structured table
# ══════════════════════════════════════════════════════════════════════════════

def _get_quarter_column_text(text):
    """
    Extract the text belonging only to the 'Quarter' column by stripping out 
    the announcement date (e.g. 'November 3, 2025'), 'Actual', or 'Revisions'.
    """
    text_lower = text.lower()
    
    # 1. Split at announcement date
    m = DATE_PATTERN.search(text)
    if m:
        return text[:m.start()]
        
    # 2. Split at 'actual' or 'revision'
    for kw in ('actual', 'revision'):
        idx = text_lower.find(kw)
        if idx != -1:
            return text[:idx]
            
    return text


def _parse_pdf_table(rows, col_centers, tol=None):
    """
    Parse all data rows into a list of blocks, one per quarter period.
    Each block:
    {
        'period':  'apr - jun',   # normalised lowercase
        'year':    2026,
        'entries': [
            {
                'type':     'Actual' | 'AnnDate' | 'Revisions',
                'ann_date': 'YYYYMMDD' or None,
                'values':   {1: float_or_None, ..., 7: float_or_None}
            },
            ...
        ]
    }

    The PDF interleaves "quarter label" rows (just "Apr - Jun" on one line,
    "2026" + data on the next) with data rows.

    IMPORTANT: Some PDF vintages (e.g. July 2025) place the period label AND
    the first estimate date AND values all on the SAME row:
        "Apr - Jun  April 28, 2025  480  554  (75)  480  0  850  (15)"
    We detect this by checking whether the period label row also contains an
    announcement date or column values, and if so, extract an entry from it.
    """
    if tol is None:
        tol = _compute_col_tolerance(col_centers)

    blocks = []
    current_block = None

    # State machine
    # We process rows sequentially. A "period start" is any row whose text
    # matches a quarter range (Jan - Mar, Apr - Jun, Jul - Sep, Oct - Dec).

    i = 0
    while i < len(rows):
        row = rows[i]
        text = _row_text(row)
        text_lower = text.lower()

        # ── Detect period label row ────────────────────────────────────────────
        period = None
        for key in config.QUARTER_MONTH_MAP:
            if key in text_lower:
                period = key
                break

        if period:
            # Save previous block
            if current_block:
                blocks.append(current_block)
            current_block = {
                'period':  period,
                'year':    None,
                'entries': [],
            }
            # The year might be on this row or the next. We look for
            # the year only in the text belonging to the 'Quarter' column.
            quarter_text = _get_quarter_column_text(text)
            year_m = re.search(r'\b(20\d{2})\b', quarter_text)
            if year_m:
                current_block['year'] = int(year_m.group(1))

            # ── MERGED ROW DETECTION (Jul 2025 / Feb 2026 style) ───────────────────
            # Some PDFs pack the period label + announcement date + values into
            # one row.  Detect this by looking for numeric values in the row.
            # IMPORTANT: do NOT derive the block year from the announcement
            # date found in this merged row (e.g. "Jan - Mar  November 3, 2025
            # 511..." should NOT set year=2025 — the year 2026 comes from the
            # NEXT row: "2026  February 2, 2026  530...").
            # The year is only set from quarter_text above (before the date),
            # or from the year-number row that follows this one.
            vals = {n: _get_col_value(row, col_centers, n, tol) for n in range(1, 8)}
            entry = _classify_row(text, vals)
            if entry:
                current_block['entries'].append(entry)
            # ──────────────────────────────────────────────────────────────────

            i += 1
            continue

        # ── Year row (immediately after period label, contains "20XX") ────────
        if current_block and current_block['year'] is None:
            quarter_text = _get_quarter_column_text(text)
            year_m = re.search(r'\b(20\d{2})\b', quarter_text)
            if year_m:
                current_block['year'] = int(year_m.group(1))
                # Also check if this row has data values
                vals = {n: _get_col_value(row, col_centers, n, tol) for n in range(1, 8)}
                entry = _classify_row(text, vals)
                if entry:
                    current_block['entries'].append(entry)
                i += 1
                continue

        # ── Data row within a block ────────────────────────────────────────────
        if current_block:
            vals = {n: _get_col_value(row, col_centers, n, tol) for n in range(1, 8)}
            entry = _classify_row(text, vals)
            if entry:
                current_block['entries'].append(entry)

        i += 1

    if current_block:
        blocks.append(current_block)

    return blocks


def _classify_row(text, vals):
    """
    Given row text and extracted column values, return an entry dict or None.
    """
    text_lower = text.lower()

    if 'actual' in text_lower:
        return {'type': 'Actual', 'ann_date': None, 'values': vals}

    if 'revision' in text_lower:
        return {'type': 'Revisions', 'ann_date': None, 'values': vals}

    # Check for announcement date
    m = DATE_PATTERN.search(text)
    if m:
        from datetime import datetime as dt
        try:
            d = dt.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", '%B %d %Y')
            ann_date = d.strftime('%Y%m%d')
            return {'type': 'AnnDate', 'ann_date': ann_date, 'values': vals}
        except ValueError:
            pass

    # Skip rows with no numeric values (likely headers or empty)
    has_values = any(v is not None for v in vals.values())
    if has_values:
        return {'type': 'Other', 'ann_date': None, 'values': vals}

    return None


# ══════════════════════════════════════════════════════════════════════════════
# Step 6: Select the right row from a block
# ══════════════════════════════════════════════════════════════════════════════

def _pick_estimate_row(block, is_quarter_of_release):
    """
    From a block's entries, pick the best estimate row.

    For "Quarter of Release":
      - If there are AnnDate rows, pick the LATEST (highest ann_date string).
      - Else fall back to Actual.
    For "Next Quarter":
      - Usually only ONE AnnDate row → use it.
      - Could also be Actual if already published.
    Returns the entry dict or None.
    """
    ann_rows = [e for e in block['entries'] if e['type'] == 'AnnDate']
    actual_rows = [e for e in block['entries'] if e['type'] == 'Actual']

    if ann_rows:
        # Sort by ann_date descending, pick latest
        ann_rows.sort(key=lambda e: e['ann_date'], reverse=True)
        return ann_rows[0]

    if actual_rows:
        return actual_rows[-1]

    return None


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def extract(pdf_path, year, quarter, period_label, date_str):
    """
    Extract 7 data points from the Sources and Uses PDF.

    Returns:
    {
        'date_str':     'YYYYMMDD',
        'year':         int,
        'quarter':      int,
        'period_label': str,
        'data': {
            'SOMARQD.SOMAREDEMP.Q':                   float or None,
            'SOMARQD.MARKETABLEBORROWING.QRELEASE.Q': float or None,
            'SOMARQD.MARKETABLEBORROWING.QNEXT.Q':    float or None,
            'SOMARQD.CHANGEINCASHBALANCE.QRELEASE.Q': float or None,
            'SOMARQD.CHANGEINCASHBALANCE.QNEXT.Q':    float or None,
            'SOMARQD.ENDOFQUARTERBALANCE.QRELEASE.Q': float or None,
            'SOMARQD.ENDOFQUARTERBALANCE.QNEXT.Q':    float or None,
        }
    }
    """
    logger.info(f"Extracting from: {pdf_path}")
    doc = fitz.open(pdf_path)
    page = doc[0]

    words = _get_words(page)
    rows = _group_into_rows(words, row_gap=3.5)
    col_centers = _find_column_centers(rows)
    tol = _compute_col_tolerance(col_centers)

    logger.info(f"Column centers: {col_centers}")
    logger.info(f"Dynamic COL_TOLERANCE: {tol:.1f} pts")
    logger.info(f"Total rows: {len(rows)}")

    blocks = _parse_pdf_table(rows, col_centers, tol)

    doc.close()

    logger.debug(f"Parsed {len(blocks)} quarter blocks:")
    for b in blocks:
        logger.debug(f"  {b['year']} {b['period']} — {len(b['entries'])} entries")
        for e in b['entries']:
            logger.debug(f"    {e['type']} {e['ann_date']} vals={e['values']}")

    # ── Find target period key ────────────────────────────────────────────────
    target_period_key = config.QUARTER_PERIOD_LABEL[quarter].lower().replace(' ', ' ')
    # Normalise to the config key format
    # e.g. "Apr - Jun" → "apr - jun"
    for key in config.QUARTER_MONTH_MAP:
        if config.QUARTER_MONTH_MAP[key] == quarter:
            target_period_key = key
            break

    next_q   = (quarter % 4) + 1
    next_yr  = year + 1 if quarter == 4 else year
    for key in config.QUARTER_MONTH_MAP:
        if config.QUARTER_MONTH_MAP[key] == next_q:
            next_period_key = key
            break

    # ── Find matching blocks ──────────────────────────────────────────────────
    target_block = None
    next_block   = None

    for b in blocks:
        if b['year'] == year and b['period'] == target_period_key:
            target_block = b
        if b['year'] == next_yr and b['period'] == next_period_key:
            next_block = b

    logger.info(
        f"Target block: {target_block['year'] if target_block else 'NOT FOUND'} "
        f"{target_period_key}"
    )
    logger.info(
        f"Next block:   {next_block['year'] if next_block else 'NOT FOUND'} "
        f"{next_period_key}"
    )

    # ── Extract values ────────────────────────────────────────────────────────
    def _vals(block, is_qr):
        if block is None:
            return None
        return _pick_estimate_row(block, is_qr)

    qr_entry  = _vals(target_block, True)
    nxt_entry = _vals(next_block, False)

    logger.info(f"Quarter-of-Release entry: {qr_entry}")
    logger.info(f"Next-Quarter entry: {nxt_entry}")

    idx = config.PDF_COL_IDX

    def _v(entry, col_key):
        if entry is None:
            return None
        col_num = col_key + 1  # col_key is 0-based, col_centers uses 1-based
        return entry['values'].get(col_num)

    # Map to our codes using col_num (1-based)
    data = {
        'SOMARQD.SOMAREDEMP.Q':
            (qr_entry['values'].get(7) if qr_entry else None),
        'SOMARQD.MARKETABLEBORROWING.QRELEASE.Q':
            (qr_entry['values'].get(2) if qr_entry else None),
        'SOMARQD.MARKETABLEBORROWING.QNEXT.Q':
            (nxt_entry['values'].get(2) if nxt_entry else None),
        'SOMARQD.CHANGEINCASHBALANCE.QRELEASE.Q':
            (qr_entry['values'].get(5) if qr_entry else None),
        'SOMARQD.CHANGEINCASHBALANCE.QNEXT.Q':
            (nxt_entry['values'].get(5) if nxt_entry else None),
        'SOMARQD.ENDOFQUARTERBALANCE.QRELEASE.Q':
            (qr_entry['values'].get(6) if qr_entry else None),
        'SOMARQD.ENDOFQUARTERBALANCE.QNEXT.Q':
            (nxt_entry['values'].get(6) if nxt_entry else None),
    }

    logger.info(f"Extracted data: {data}")

    return {
        'date_str':     date_str,
        'year':         year,
        'quarter':      quarter,
        'period_label': period_label,
        'data':         data,
    }
