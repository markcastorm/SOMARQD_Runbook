"""
file_generator.py — Write SOMARQD output files: DATA xlsx, META xlsx, ZIP.

Public API
----------
generate_files(extraction_result) -> dict
    Writes:
      SOMARQD_DATA_<YYYYMMDD>.xlsx  — two header rows + exactly 2 data rows
                                      (current release quarter and next quarter)
      SOMARQD_META_<YYYYMMDD>.xlsx  — metadata file
      SOMARQD_<YYYYMMDD>.zip        — both files zipped
    To:
      config.OUTPUT_DIR/<timestamp>/   (timestamped run folder)
      config.OUTPUT_DIR/latest/        (always overwritten with latest)
    Returns {'data_path': ..., 'meta_path': ..., 'zip_path': ...}
"""

import os
import shutil
import zipfile
from datetime import datetime

import openpyxl
import pandas as pd

import config


def _period_key(year, quarter):
    """e.g. (2026, 2) → '2026-Q2'"""
    return f"{year}-Q{quarter}"


# ══════════════════════════════════════════════════════════════════════════════
# DATA xlsx
# ══════════════════════════════════════════════════════════════════════════════

def _write_data(data_dict, date_str, run_dir):
    """
    Write the DATA xlsx file.
    Row 0: '' + codes
    Row 1: '' + descriptions
    Row 2+: period + values (sorted chronologically)
    """
    path = os.path.join(run_dir, f'SOMARQD_DATA_{date_str}.xlsx')
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Data'

    # Header rows
    ws.append(config.HEADER_ROW_CODES)
    ws.append(config.HEADER_ROW_LABELS)

    codes = [c['code'] for c in config.COLUMNS]
    for period in sorted(data_dict.keys()):
        row = [period]
        period_data = data_dict[period]
        for code in codes:
            val = period_data.get(code, config.NA_OUTPUT_VALUE)
            if val is None or val == '':
                row.append(config.NA_OUTPUT_VALUE)
            else:
                try:
                    row.append(float(val))
                except (TypeError, ValueError):
                    row.append(val)
        ws.append(row)

    wb.save(path)
    return path


# ══════════════════════════════════════════════════════════════════════════════
# META xlsx
# ══════════════════════════════════════════════════════════════════════════════

def _write_meta(date_str, run_dir):
    """Write the META xlsx file."""
    path = os.path.join(run_dir, f'SOMARQD_META_{date_str}.xlsx')
    rows = []
    for c in config.COLUMNS:
        row = dict(config.META_STATIC)
        row['CODE']          = c['code']
        row['CODE_MNEMONIC'] = c['code'].rsplit('.', 1)[0]   # strip trailing .Q
        row['DESCRIPTION']   = c['description']
        rows.append(row)

    pd.DataFrame(rows, columns=config.META_COLUMNS).to_excel(
        path, index=False, engine='openpyxl'
    )
    return path


# ══════════════════════════════════════════════════════════════════════════════
# ZIP
# ══════════════════════════════════════════════════════════════════════════════

def _write_zip(date_str, run_dir, files):
    path = os.path.join(run_dir, f'SOMARQD_{date_str}.zip')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, os.path.basename(f))
    return path


# ══════════════════════════════════════════════════════════════════════════════
# Cleanup
# ══════════════════════════════════════════════════════════════════════════════

def _cleanup_old_runs(keep=10):
    """
    Remove old timestamped run directories, keeping the N most recent.
    Never touches 'latest/'.
    """
    if not os.path.exists(config.OUTPUT_DIR):
        return
    entries = []
    for name in os.listdir(config.OUTPUT_DIR):
        if name == 'latest':
            continue
        full = os.path.join(config.OUTPUT_DIR, name)
        if os.path.isdir(full):
            entries.append((name, full))
    # Sort by name (timestamp prefix YYYYMMDD_HHMMSS → chronological)
    entries.sort(key=lambda x: x[0])
    # Remove oldest beyond keep limit
    while len(entries) > keep:
        old_name, old_path = entries.pop(0)
        shutil.rmtree(old_path, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def generate_files(extraction_result):
    """
    extraction_result: dict returned by extractor.extract()
    {
        'date_str':     'YYYYMMDD',
        'year':         int,
        'quarter':      int,
        'period_label': str,
        'data': { code: value, ... }
    }

    Returns {'data_path': ..., 'meta_path': ..., 'zip_path': ...}
    """
    date_str = extraction_result['date_str']
    year     = extraction_result['year']
    quarter  = extraction_result['quarter']
    new_data = extraction_result['data']

    # ── Create local data dict with exactly 2 rows ────────────────────────────
    run_data = {}

    # Period of release row
    release_period = _period_key(year, quarter)
    next_q   = (quarter % 4) + 1
    next_yr  = year + 1 if quarter == 4 else year
    next_period = _period_key(next_yr, next_q)

    codes_release = [
        'SOMARQD.SOMAREDEMP.Q',
        'SOMARQD.MARKETABLEBORROWING.QRELEASE.Q',
        'SOMARQD.CHANGEINCASHBALANCE.QRELEASE.Q',
        'SOMARQD.ENDOFQUARTERBALANCE.QRELEASE.Q',
    ]
    codes_next = [
        'SOMARQD.MARKETABLEBORROWING.QNEXT.Q',
        'SOMARQD.CHANGEINCASHBALANCE.QNEXT.Q',
        'SOMARQD.ENDOFQUARTERBALANCE.QNEXT.Q',
    ]
    all_codes = [c['code'] for c in config.COLUMNS]

    # Initialize periods
    run_data[release_period] = {c: config.NA_OUTPUT_VALUE for c in all_codes}
    run_data[next_period] = {c: config.NA_OUTPUT_VALUE for c in all_codes}

    # Write release-quarter values into release_period row
    for code in codes_release:
        val = new_data.get(code)
        run_data[release_period][code] = val if val is not None else config.NA_OUTPUT_VALUE

    # Write next-quarter values into next_period row
    for code in codes_next:
        val = new_data.get(code)
        run_data[next_period][code] = val if val is not None else config.NA_OUTPUT_VALUE

    # ── Write output files ────────────────────────────────────────────────────
    run_stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_dir   = os.path.join(config.OUTPUT_DIR, run_stamp)
    os.makedirs(run_dir, exist_ok=True)

    data_path = _write_data(run_data, date_str, run_dir)
    meta_path = _write_meta(date_str, run_dir)
    zip_path  = _write_zip(date_str, run_dir, [data_path, meta_path])

    # ── Copy to latest/ ───────────────────────────────────────────────────────
    latest_dir = os.path.join(config.OUTPUT_DIR, 'latest')
    if os.path.exists(latest_dir):
        shutil.rmtree(latest_dir)
    os.makedirs(latest_dir)
    for src in [data_path, meta_path, zip_path]:
        shutil.copy2(src, os.path.join(latest_dir, os.path.basename(src)))

    # ── Cleanup old runs ──────────────────────────────────────────────────────
    _cleanup_old_runs(keep=10)

    return {
        'data_path': data_path,
        'meta_path': meta_path,
        'zip_path':  zip_path,
    }
