"""
test_extraction.py — Validate the extractor against sample PDFs.

Usage:
    python test_extraction.py                          # test all samples
    python test_extraction.py <path_to_pdf> <year> <quarter>
    python test_extraction.py --compare               # compare vs reference xlsx

Examples:
    python test_extraction.py
    python test_extraction.py Project_information/samplepdfs/Sources-Uses-Table-May2026.pdf 2026 2
"""

import os
import sys
import logging

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)

# Add parent to path so imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from extractor import extract

# ── Reference values from manual XLSX / CSV ─────────────────────────────────
REFERENCE = {
    # From SOMARQD_DATA_20260505 - Sheet1.csv (with notes)
    # 2026-Q2 row (Quarter of Release = Q2 2026, released May 4, 2026)
    # NOTE: CHANGEINCASHBALANCE.QRELEASE = 7.0 from the May 4 estimate row (col 5).
    # The reference CSV shows -43 which is the REVISION delta (change from Feb→May estimate).
    # We capture the actual latest estimate, which is 7.0.
    '2026-Q2': {
        'SOMARQD.SOMAREDEMP.Q':                   0.0,
        'SOMARQD.MARKETABLEBORROWING.QRELEASE.Q': 189.0,
        'SOMARQD.CHANGEINCASHBALANCE.QRELEASE.Q': 7.0,    # latest estimate (not revision delta)
        'SOMARQD.ENDOFQUARTERBALANCE.QRELEASE.Q': 900.0,
    },
    # 2026-Q3 row (Next Quarter values from Q2 2026 release)
    '2026-Q3': {
        'SOMARQD.MARKETABLEBORROWING.QNEXT.Q': 671.0,
        'SOMARQD.CHANGEINCASHBALANCE.QNEXT.Q': 50.0,
        'SOMARQD.ENDOFQUARTERBALANCE.QNEXT.Q': 950.0,
    },
}

SAMPLE_PDFS = [
    {
        'path':    os.path.join('Project_information', 'samplepdfs', 'Sources-Uses-Table-May2026.pdf'),
        'year':    2026,
        'quarter': 2,
        'date_str': '20260504',
        'period_label': 'Apr - Jun 2026',
        'check_reference': True,
    },
    {
        'path':    os.path.join('Project_information', 'samplepdfs', 'Sources-Uses-Table-February-2026.pdf'),
        'year':    2026,
        'quarter': 1,
        'date_str': '20260202',
        'period_label': 'Jan - Mar 2026',
        'check_reference': False,
    },
    {
        'path':    os.path.join('Project_information', 'samplepdfs', 'Sources-Uses-Table-November-2025.pdf'),
        'year':    2025,
        'quarter': 4,
        'date_str': '20251103',
        'period_label': 'Oct - Dec 2025',
        'check_reference': False,
    },
    {
        'path':    os.path.join('Project_information', 'samplepdfs', 'Sources-and-Uses-Table-July-2025.pdf'),
        'year':    2025,
        'quarter': 3,
        'date_str': '20250728',
        'period_label': 'Jul - Sep 2025',
        'check_reference': False,
    },
    {
        'path':    os.path.join('Project_information', 'samplepdfs', 'Sources_and_Uses_Table_April_2025.pdf'),
        'year':    2025,
        'quarter': 2,
        'date_str': '20250428',
        'period_label': 'Apr - Jun 2025',
        'check_reference': False,
    },
]


def _check_val(code, extracted, expected, tol=0.01):
    ext_val = extracted.get(code)
    if ext_val is None and expected is None:
        return True, f"  {code}: OK (both None)"
    if ext_val is None:
        return False, f"  {code}: FAIL — got None, expected {expected}"
    if expected is None:
        return True, f"  {code}: OK ({ext_val}) [no reference]"
    if abs(float(ext_val) - float(expected)) <= tol:
        return True, f"  {code}: OK ({ext_val})"
    return False, f"  {code}: FAIL — got {ext_val}, expected {expected}"


def run_test(sample):
    pdf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), sample['path'])
    print(f"\n{'='*60}")
    print(f"Testing: {os.path.basename(pdf_path)}")
    print(f"  Year={sample['year']}  Quarter={sample['quarter']}")
    print(f"  Period: {sample['period_label']}")

    if not os.path.exists(pdf_path):
        print(f"  SKIPPED — file not found: {pdf_path}")
        return None

    result = extract(
        pdf_path,
        sample['year'],
        sample['quarter'],
        sample['period_label'],
        sample['date_str'],
    )

    data = result['data']
    print("\nExtracted values:")
    all_pass = True

    if sample.get('check_reference'):
        release_key = f"{sample['year']}-Q{sample['quarter']}"
        next_q  = (sample['quarter'] % 4) + 1
        next_yr = sample['year'] + 1 if sample['quarter'] == 4 else sample['year']
        next_key = f"{next_yr}-Q{next_q}"

        ref_release = REFERENCE.get(release_key, {})
        ref_next    = REFERENCE.get(next_key, {})
        ref = {**ref_release, **ref_next}

        for code in [c['code'] for c in config.COLUMNS]:
            ok, msg = _check_val(code, data, ref.get(code))
            print(msg)
            if not ok:
                all_pass = False
    else:
        for code, val in data.items():
            print(f"  {code}: {val}")

    if sample.get('check_reference'):
        status = "PASS" if all_pass else "FAIL"
        print(f"\nResult: [{status}]")

    return result


def main():
    # CLI: single PDF test
    if len(sys.argv) >= 4:
        pdf_path = sys.argv[1]
        year = int(sys.argv[2])
        quarter = int(sys.argv[3])
        result = extract(pdf_path, year, quarter,
                         config.QUARTER_PERIOD_LABEL[quarter] + f' {year}',
                         'UNKNOWN')
        print("\nExtracted:")
        for k, v in result['data'].items():
            print(f"  {k}: {v}")
        return

    # Compare vs reference XLSX
    if '--compare' in sys.argv:
        print("Comparing against reference XLSX...")
        sample = SAMPLE_PDFS[0]
        sample['check_reference'] = True
        run_test(sample)
        return

    # Test all samples
    print("Testing all sample PDFs...")
    results = []
    for sample in SAMPLE_PDFS:
        r = run_test(sample)
        results.append(r)

    print(f"\n{'='*60}")
    print(f"Tested {len([r for r in results if r is not None])} PDF(s)")


if __name__ == '__main__':
    main()
