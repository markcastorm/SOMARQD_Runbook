"""
config.py — All configuration for the SOMARQD pipeline.

SOMARQD: US Treasury Quarterly Refunding Financing Estimates
Provider: AfricaAI | Dataset: SOMARQD | Country: USA | Frequency: Quarterly

Source: https://home.treasury.gov/policy-issues/financing-the-government/quarterly-refunding/
        quarterly-refunding-archives/quarterly-refunding-financing-estimates-by-calendar-year
"""

import os

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, 'downloads')
OUTPUT_DIR   = os.path.join(BASE_DIR, 'output')

# ── Source ─────────────────────────────────────────────────────────────────────
ARCHIVE_URL = (
    'https://home.treasury.gov/policy-issues/financing-the-government/'
    'quarterly-refunding/quarterly-refunding-archives/'
    'quarterly-refunding-financing-estimates-by-calendar-year'
)
BASE_DOMAIN = 'https://home.treasury.gov'

# ── Browser ────────────────────────────────────────────────────────────────────
HEADLESS_MODE = True      # always True — Docker has no display
WAIT_TIMEOUT  = 60        # seconds
PAGE_LOAD_SLEEP = 3       # extra sleep after navigation

# ── Job identity ───────────────────────────────────────────────────────────────
JOB_NAME = 'SOMARQD'

# ── Target selection ───────────────────────────────────────────────────────────
# TARGET_YEAR    : int or None
#   None  → pick the latest year that has at least one clickable quarter link
#   int   → e.g. 2025
# TARGET_QUARTER : int (1-4) or None
#   None  → within the selected year, pick the latest clickable quarter link
#   int   → force a specific quarter number (1=Q1, 2=Q2, 3=Q3, 4=Q4)
TARGET_YEAR    = None   # None = auto-detect latest available
TARGET_QUARTER = None   # None = auto-detect latest available in that year

# ── Processed-data cache ───────────────────────────────────────────────────────
# Set to True to skip the "already processed?" check and force re-processing.
FORCE_REPROCESS = False
PROCESSED_LOG   = os.path.join(BASE_DIR, 'processed.json')

# ── PDF keyword for "Sources and Uses Table" link ─────────────────────────────
# The press-release page contains a link with one of these text patterns.
# We search case-insensitively for any of them.
SOURCES_USES_LINK_KEYWORDS = [
    'sources and uses table',
    'view sources and uses table',
    'sources and uses',
]

# ── NA / output fill ───────────────────────────────────────────────────────────
NA_OUTPUT_VALUE = ''

# ══════════════════════════════════════════════════════════════════════════════
# ABSOLUTE COLUMN MAPPING
# These are the exact codes (row 0) and descriptions (row 1) used in the
# DATA output file. Order is absolute and must never change unless the
# upstream data structure changes.
# ══════════════════════════════════════════════════════════════════════════════

COLUMNS = [
    {
        'code':        'SOMARQD.SOMAREDEMP.Q',
        'description': 'SOMA Redemptions',
        # PDF column index (0-based) in the Sources and Uses table
        # Col (7) = SOMA Redemptions (Memo)
        'pdf_col_index': 6,      # 0-based: cols are (1),(2),(3),(4),(5),(6),(7)
        'pdf_col_label': 'SOMA Redemptions',
    },
    {
        'code':        'SOMARQD.MARKETABLEBORROWING.QRELEASE.Q',
        'description': 'Marketable Borrowing, Quarter of Release',
        # Col (2) = Marketable Borrowing — for the "Quarter of Release" row
        'pdf_col_index': 1,
        'pdf_col_label': 'Marketable Borrowing',
        'row_type': 'quarter_of_release',
    },
    {
        'code':        'SOMARQD.MARKETABLEBORROWING.QNEXT.Q',
        'description': 'Marketable Borrowing, Next Quarter',
        'pdf_col_index': 1,
        'pdf_col_label': 'Marketable Borrowing',
        'row_type': 'next_quarter',
    },
    {
        'code':        'SOMARQD.CHANGEINCASHBALANCE.QRELEASE.Q',
        'description': 'Change in Cash balance, Quarter of Release',
        # Col (5) = Change in Cash Balance
        'pdf_col_index': 4,
        'pdf_col_label': 'Change in Cash Balance',
        'row_type': 'quarter_of_release',
    },
    {
        'code':        'SOMARQD.CHANGEINCASHBALANCE.QNEXT.Q',
        'description': 'Change in Cash balance, Next Quarter',
        'pdf_col_index': 4,
        'pdf_col_label': 'Change in Cash Balance',
        'row_type': 'next_quarter',
    },
    {
        'code':        'SOMARQD.ENDOFQUARTERBALANCE.QRELEASE.Q',
        'description': 'End-Of-Quarter Cash Balance, Quarter of Release',
        # Col (6) = End-Of-Quarter Cash Balance
        'pdf_col_index': 5,
        'pdf_col_label': 'End-Of-Quarter Cash Balance',
        'row_type': 'quarter_of_release',
    },
    {
        'code':        'SOMARQD.ENDOFQUARTERBALANCE.QNEXT.Q',
        'description': 'End-Of-Quarter Cash Balance, Next Quarter',
        'pdf_col_index': 5,
        'pdf_col_label': 'End-Of-Quarter Cash Balance',
        'row_type': 'next_quarter',
    },
]

# Convenience: ordered codes and descriptions for header rows
HEADER_ROW_CODES  = [''] + [c['code']        for c in COLUMNS]
HEADER_ROW_LABELS = [''] + [c['description'] for c in COLUMNS]

# ── PDF table column order (as they appear left→right in the PDF) ─────────────
# Quarter | Announcement Date | (1)Financing Need | (2)Marketable Borrowing |
# (3)All Other Sources | (4)Total | (5)Change in Cash Balance |
# (6)End-Of-Quarter Cash Balance | (7)SOMA Redemptions (Memo)
#
# 0-based indices within the data-value columns (after Quarter + Announcement Date):
PDF_COL_IDX = {
    'financing_need':          0,   # col (1)
    'marketable_borrowing':    1,   # col (2)
    'all_other_sources':       2,   # col (3)
    'total':                   3,   # col (4)
    'change_in_cash_balance':  4,   # col (5)
    'end_of_quarter_balance':  5,   # col (6)
    'soma_redemptions':        6,   # col (7)
}

# Quarter month ranges — used to map "Apr - Jun" → Q2 etc.
QUARTER_MONTH_MAP = {
    'jan - mar': 1,
    'apr - jun': 2,
    'jul - sep': 3,
    'oct - dec': 4,
}

# Reverse: quarter number → canonical period label in the PDF
QUARTER_PERIOD_LABEL = {
    1: 'Jan - Mar',
    2: 'Apr - Jun',
    3: 'Jul - Sep',
    4: 'Oct - Dec',
}

# ── META file columns (absolute) ───────────────────────────────────────────────
META_COLUMNS = [
    'CODE', 'CODE_MNEMONIC', 'DESCRIPTION', 'FREQUENCY', 'MULTIPLIER',
    'AGGREGATION_TYPE', 'UNIT_TYPE', 'DATA_TYPE', 'DATA_UNIT',
    'SEASONALLY_ADJUSTED', 'ANNUALIZED', 'PROVIDER_MEASURE_URL',
    'PROVIDER', 'SOURCE', 'SOURCE_DESCRIPTION', 'COUNTRY', 'DATASET',
]

META_STATIC = {
    'FREQUENCY':          'Q',
    'MULTIPLIER':         9,          # values are in billions
    'AGGREGATION_TYPE':   'UNDEFINED',
    'UNIT_TYPE':          'LEVEL',
    'DATA_TYPE':          'REAL',
    'DATA_UNIT':          'USD',
    'SEASONALLY_ADJUSTED':'NSA',
    'ANNUALIZED':         False,
    'PROVIDER_MEASURE_URL': (
        'https://home.treasury.gov/policy-issues/financing-the-government/'
        'quarterly-refunding/quarterly-refunding-archives/'
        'quarterly-refunding-financing-estimates-by-calendar-year'
    ),
    'PROVIDER':            'AfricaAI',
    'SOURCE':              'US Treasury',
    'SOURCE_DESCRIPTION':  'U.S. Department of the Treasury — Quarterly Refunding Financing Estimates',
    'COUNTRY':             'USA',
    'DATASET':             'SOMARQD',
}
