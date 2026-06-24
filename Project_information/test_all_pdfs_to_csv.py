"""
test_all_pdfs_to_csv.py — Test extractor on ALL sample PDFs and write results to CSV.

Usage:
    python test_all_pdfs_to_csv.py

Output:
    - Prints per-PDF extraction results
    - Saves all results to: Project_information/extraction_test_results.csv
    - Shows PASS/FAIL verdict per PDF and field

PDF       Q    SOMAREDEMP  MB.QREL  MB.QNEXT  CCB.QREL  CCB.QNEXT  EOQ.QREL  EOQ.QNEXT
--------------------------------------------------------------------------------------------
Nov-25   Q4     -10.0     569.0    578.0     -41.0       0.0      850.0      850.0
"""

import os
import sys
import csv
import logging

logging.basicConfig(
    stream=sys.stdout,
    level=logging.WARNING,    # suppress INFO during CSV run; use DEBUG for deep trace
    format='%(asctime)s [%(levelname)s] %(message)s',
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from extractor import extract

# ── Sample PDF definitions ────────────────────────────────────────────────────
# Each entry: path, year, quarter, date_str, period_label, expected (optional)
SAMPLES = [
    {
        'label':        '2026-Q2 (May 2026)',
        'path':         os.path.join('Project_information', 'samplepdfs', 'Sources-Uses-Table-May2026.pdf'),
        'year':         2026,
        'quarter':      2,
        'date_str':     '20260504',
        'period_label': 'Apr - Jun 2026',
        # Reference values from manual XLSX (SOMARQD_DATA_20260505.csv)
        'expected': {
            'SOMARQD.SOMAREDEMP.Q':                   0.0,
            'SOMARQD.MARKETABLEBORROWING.QRELEASE.Q': 189.0,
            'SOMARQD.MARKETABLEBORROWING.QNEXT.Q':    671.0,
            'SOMARQD.CHANGEINCASHBALANCE.QRELEASE.Q': 7.0,
            'SOMARQD.CHANGEINCASHBALANCE.QNEXT.Q':    50.0,
            'SOMARQD.ENDOFQUARTERBALANCE.QRELEASE.Q': 900.0,
            'SOMARQD.ENDOFQUARTERBALANCE.QNEXT.Q':    950.0,
        },
    },
    {
        'label':        '2026-Q1 (Feb 2026)',
        'path':         os.path.join('Project_information', 'samplepdfs', 'Sources-Uses-Table-February-2026.pdf'),
        'year':         2026,
        'quarter':      1,
        'date_str':     '20260202',
        'period_label': 'Jan - Mar 2026',
        # Reference: From screenshot / manual verification
        # Jan-Mar 2026 (Feb 2 estimate): MB=574, CCB=-23, EOQ=850, SOMA=0
        # Apr-Jun 2026 (Feb 2 next-Q estimate): MB=109, CCB=50, EOQ=900
        'expected': {
            'SOMARQD.SOMAREDEMP.Q':                   0.0,
            'SOMARQD.MARKETABLEBORROWING.QRELEASE.Q': 574.0,
            'SOMARQD.MARKETABLEBORROWING.QNEXT.Q':    109.0,
            'SOMARQD.CHANGEINCASHBALANCE.QRELEASE.Q': -23.0,
            'SOMARQD.CHANGEINCASHBALANCE.QNEXT.Q':    50.0,
            'SOMARQD.ENDOFQUARTERBALANCE.QRELEASE.Q': 850.0,
            'SOMARQD.ENDOFQUARTERBALANCE.QNEXT.Q':    900.0,
        },
    },
    {
        'label':        '2025-Q4 (Nov 2025)',
        'path':         os.path.join('Project_information', 'samplepdfs', 'Sources-Uses-Table-November-2025.pdf'),
        'year':         2025,
        'quarter':      4,
        'date_str':     '20251103',
        'period_label': 'Oct - Dec 2025',
        # Reference: From screenshot (7.png)
        # Oct-Dec 2025 (Nov 3 estimate): MB=569, CCB=-41, EOQ=850, SOMA=-10
        # Jan-Mar 2026 (Nov 3 next-Q):   MB=578, CCB=0,   EOQ=850, SOMA=0
        'expected': {
            'SOMARQD.SOMAREDEMP.Q':                   -10.0,
            'SOMARQD.MARKETABLEBORROWING.QRELEASE.Q': 569.0,
            'SOMARQD.MARKETABLEBORROWING.QNEXT.Q':    578.0,
            'SOMARQD.CHANGEINCASHBALANCE.QRELEASE.Q': -41.0,
            'SOMARQD.CHANGEINCASHBALANCE.QNEXT.Q':    0.0,   # ← THE FAILING FIELD (was None)
            'SOMARQD.ENDOFQUARTERBALANCE.QRELEASE.Q': 850.0,
            'SOMARQD.ENDOFQUARTERBALANCE.QNEXT.Q':    850.0,
        },
    },
    {
        'label':        '2025-Q3 (Jul 2025)',
        'path':         os.path.join('Project_information', 'samplepdfs', 'Sources-and-Uses-Table-July-2025.pdf'),
        'year':         2025,
        'quarter':      3,
        'date_str':     '20250728',
        'period_label': 'Jul - Sep 2025',
        # Reference: From screenshot (7.png)
        # Jul-Sep 2025 (Jul 28 estimate): MB=1007, CCB=393, EOQ=850, SOMA=-15
        # Oct-Dec 2025 (Jul 28 next-Q):   MB=590,  CCB=0,   EOQ=850, SOMA=-15
        'expected': {
            'SOMARQD.SOMAREDEMP.Q':                   -15.0,
            'SOMARQD.MARKETABLEBORROWING.QRELEASE.Q': 1007.0,
            'SOMARQD.MARKETABLEBORROWING.QNEXT.Q':    590.0,
            'SOMARQD.CHANGEINCASHBALANCE.QRELEASE.Q': 393.0,
            'SOMARQD.CHANGEINCASHBALANCE.QNEXT.Q':    0.0,   # ← also fixed
            'SOMARQD.ENDOFQUARTERBALANCE.QRELEASE.Q': 850.0,
            'SOMARQD.ENDOFQUARTERBALANCE.QNEXT.Q':    850.0,
        },
    },
    {
        'label':        '2025-Q2 (Apr 2025)',
        'path':         os.path.join('Project_information', 'samplepdfs', 'Sources_and_Uses_Table_April_2025.pdf'),
        'year':         2025,
        'quarter':      2,
        'date_str':     '20250428',
        'period_label': 'Apr - Jun 2025',
        # Reference: From screenshot (7.png)
        # Apr-Jun 2025 (Apr 28 estimate): MB=514, CCB=444, EOQ=850, SOMA=-15
        # Jul-Sep 2025 (Apr 28 next-Q):   MB=554, CCB=0,   EOQ=850, SOMA=-15
        'expected': {
            'SOMARQD.SOMAREDEMP.Q':                   -15.0,
            'SOMARQD.MARKETABLEBORROWING.QRELEASE.Q': 514.0,
            'SOMARQD.MARKETABLEBORROWING.QNEXT.Q':    554.0,
            'SOMARQD.CHANGEINCASHBALANCE.QRELEASE.Q': 444.0,
            'SOMARQD.CHANGEINCASHBALANCE.QNEXT.Q':    0.0,   # ← also fixed
            'SOMARQD.ENDOFQUARTERBALANCE.QRELEASE.Q': 850.0,
            'SOMARQD.ENDOFQUARTERBALANCE.QNEXT.Q':    850.0,
        },
    },
]

CODES = [c['code'] for c in config.COLUMNS]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt(v):
    """Format a value for display."""
    if v is None:
        return 'None'
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def _check(code, extracted, expected, tol=0.01):
    """Returns (pass:bool, status_str, delta_str)"""
    ev = extracted.get(code)
    xv = expected.get(code) if expected else None

    if xv is None:
        # No reference → just report the value
        return None, 'NO_REF', ''

    if ev is None and xv is not None:
        return False, 'FAIL(None)', f'expected {xv}'

    if ev is not None and abs(float(ev) - float(xv)) <= tol:
        return True, 'PASS', ''

    return False, f'FAIL({ev})', f'expected {xv}'


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    base = os.path.dirname(os.path.abspath(__file__))
    out_csv = os.path.join(base, 'Project_information', 'extraction_test_results.csv')

    csv_rows = []
    all_pass = True

    for s in SAMPLES:
        pdf_path = os.path.join(base, s['path'])
        label = s['label']
        expected = s.get('expected', {})

        print(f"\n{'='*70}")
        print(f"PDF: {label}")
        print(f"  File : {os.path.basename(pdf_path)}")
        print(f"  Year : {s['year']}  Quarter: Q{s['quarter']}")

        if not os.path.exists(pdf_path):
            print(f"  SKIPPED — file not found")
            continue

        result = extract(
            pdf_path,
            s['year'],
            s['quarter'],
            s['period_label'],
            s['date_str'],
        )
        data = result['data']

        print(f"\n  {'CODE':<50}  {'EXTRACTED':>12}  {'STATUS':<18}  NOTE")
        print(f"  {'-'*50}  {'-'*12}  {'-'*18}  {'-'*20}")

        row = {
            'label':    label,
            'pdf_file': os.path.basename(pdf_path),
            'year':     s['year'],
            'quarter':  s['quarter'],
            'date_str': s['date_str'],
        }

        for code in CODES:
            ev = data.get(code)
            ok, status, note = _check(code, data, expected)

            if ok is False:
                all_pass = False

            print(f"  {code:<50}  {_fmt(ev):>12}  {status:<18}  {note}")
            row[code] = _fmt(ev)
            row[code + '_status'] = status

        csv_rows.append(row)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"\nOverall: {'ALL PASS [OK]' if all_pass else 'SOME FAILURES [!!]'}")

    # ── Write CSV ─────────────────────────────────────────────────────────────
    fieldnames = (
        ['label', 'pdf_file', 'year', 'quarter', 'date_str'] +
        [code for code in CODES] +
        [code + '_status' for code in CODES]
    )
    with open(out_csv, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in csv_rows:
            w.writerow({k: row.get(k, '') for k in fieldnames})

    print(f"\nResults saved to: {out_csv}")
    return 0 if all_pass else 1


if __name__ == '__main__':
    sys.exit(main())
