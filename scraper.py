"""
scraper.py — Download the Sources and Uses Table PDF for SOMARQD.

Strategy:
  1. Try requests + BeautifulSoup (fast, no JS needed for static HTML table).
  2. Fall back to Selenium stealth if the first attempt fails.

The scraper:
  1. Loads the archive page to find quarterly links (determines year+quarter).
  2. Clicks (or follows) the quarter press-release link.
  3. On the press-release page, finds the "Sources and Uses Table" PDF link.
  4. Downloads the PDF to downloads/<timestamp>/<year>/Q<quarter>/

Returns a dict:
    {
        'pdf_path'  : str,    # absolute local path to downloaded PDF
        'year'      : int,
        'quarter'   : int,    # 1-4
        'date_str'  : str,    # 'YYYYMMDD' from the press-release page date
        'period_label': str,  # e.g. 'Apr - Jun 2026'
    }
"""

import os
import re
import sys
import time
import json
import logging
import subprocess
from datetime import datetime

import requests
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)

# ── quarter quarter ordering: Q4=highest priority descending ──────────────────
QUARTER_ORDER = [4, 3, 2, 1]


# ══════════════════════════════════════════════════════════════════════════════
# Chrome detection (cross-platform)
# ══════════════════════════════════════════════════════════════════════════════

def _get_chrome_version():
    """Detect installed Chrome major version on Windows or Linux."""
    if sys.platform == 'win32':
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Google\Chrome\BLBeacon'
            )
            ver = winreg.QueryValueEx(key, 'version')[0]
            return ver.split('.')[0]
        except Exception:
            pass
        # Also check HKLM
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r'SOFTWARE\Google\Chrome\BLBeacon'
            )
            ver = winreg.QueryValueEx(key, 'version')[0]
            return ver.split('.')[0]
        except Exception:
            pass

    # Linux / Docker
    for cmd in ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser']:
        try:
            out = subprocess.check_output(
                [cmd, '--version'], stderr=subprocess.DEVNULL
            ).decode()
            return out.strip().split()[-1].split('.')[0]
        except Exception:
            continue
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _make_run_dir(year, quarter):
    """Create timestamped download directory for this run."""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_dir = os.path.join(
        config.DOWNLOAD_DIR, ts, str(year), f'Q{quarter}'
    )
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


def _parse_archive_html(html):
    """
    Parse the archive page HTML to build a dict of available quarter links.

    Returns:
        {
            year (int): {
                quarter (int): url_or_None   # None if not yet a link
            }
        }
    """
    soup = BeautifulSoup(html, 'html.parser')

    # The table has <th id="YYYY"> for year headers and then a row of <th> per quarter
    # Quarter columns are: 4th Quarter | 3rd Quarter | 2nd Quarter | 1st Quarter
    quarters_by_name = {
        '4th quarter': 4,
        '3rd quarter': 3,
        '2nd quarter': 2,
        '1st quarter': 1,
    }

    result = {}
    current_year = None

    # Find the main table
    table = soup.find('table')
    if not table:
        return result

    for tr in table.find_all('tr'):
        ths = tr.find_all('th')
        if not ths:
            continue

        # Year header row: single <th colspan="4" id="YYYY">
        if len(ths) == 1:
            th = ths[0]
            year_id = th.get('id', '')
            if re.match(r'^\d{4}$', year_id.strip()):
                current_year = int(year_id.strip())
                result[current_year] = {}
            continue

        # Quarter link row: 4 <th> cells (4th, 3rd, 2nd, 1st Quarter)
        if current_year is not None and len(ths) == 4:
            for th in ths:
                text = th.get_text(strip=True).lower()
                # Strip zero-width spaces and similar
                text = text.replace('\u200b', '').strip()
                qnum = None
                for qname, qn in quarters_by_name.items():
                    if qname in text:
                        qnum = qn
                        break
                if qnum is None:
                    continue

                a = th.find('a')
                if a and a.get('href'):
                    href = a['href'].strip()
                    if href.startswith('http'):
                        result[current_year][qnum] = href
                    else:
                        result[current_year][qnum] = config.BASE_DOMAIN + href
                else:
                    result[current_year][qnum] = None   # link exists but not clickable

    return result


def _select_target(available):
    """
    Given the availability dict, return (year, quarter, url).
    Applies TARGET_YEAR and TARGET_QUARTER from config.
    """
    target_year = config.TARGET_YEAR
    target_quarter = config.TARGET_QUARTER

    if target_year is None:
        # Pick latest year that has at least one active link
        for year in sorted(available.keys(), reverse=True):
            quarters = available[year]
            for q in QUARTER_ORDER:
                if quarters.get(q) is not None:
                    if target_quarter is None or q == target_quarter:
                        return year, q, quarters[q]
        raise RuntimeError("No available quarter links found on the archive page.")

    # Specific year requested
    if target_year not in available:
        raise RuntimeError(f"Year {target_year} not found on the archive page.")

    quarters = available[target_year]
    if target_quarter is not None:
        url = quarters.get(target_quarter)
        if url is None:
            raise RuntimeError(
                f"Quarter {target_quarter} for year {target_year} is not yet available."
            )
        return target_year, target_quarter, url

    # Find latest available quarter for that year
    for q in QUARTER_ORDER:
        if quarters.get(q) is not None:
            return target_year, q, quarters[q]

    raise RuntimeError(f"No available quarter links found for year {target_year}.")


def _extract_page_date(html):
    """
    Extract publication date from press-release page HTML.
    Looks for <time datetime="..."> or a visible date like "May 4, 2026".
    Returns 'YYYYMMDD' string.
    """
    soup = BeautifulSoup(html, 'html.parser')

    # Try specific publication date time element
    time_el = None
    pub_div = soup.find(class_='field--name-field-news-publication-date')
    if pub_div:
        time_el = pub_div.find('time', {'datetime': True})
    
    if not time_el:
        # Fallback to any time element whose parent is not a sidebar/news-row list item
        for el in soup.find_all('time', {'datetime': True}):
            parent_classes = el.parent.get('class', []) if el.parent else []
            if 'mm-news-row' not in parent_classes:
                time_el = el
                break

    if not time_el:
        # Generic fallback
        time_el = soup.find('time', {'datetime': True})

    if time_el:
        dt_str = time_el['datetime']
        m = re.match(r'(\d{4})-(\d{2})-(\d{2})', dt_str)
        if m:
            return f"{m.group(1)}{m.group(2)}{m.group(3)}"

    # Try visible date pattern e.g. "May 4, 2026" or "January 5, 2026"
    text = soup.get_text(' ')
    m = re.search(
        r'\b(January|February|March|April|May|June|July|August|September|'
        r'October|November|December)\s+(\d{1,2}),\s+(\d{4})\b',
        text
    )
    if m:
        from datetime import datetime as dt
        try:
            d = dt.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", '%B %d %Y')
            return d.strftime('%Y%m%d')
        except ValueError:
            pass

    logger.warning("Could not extract date from press-release page; using today.")
    return datetime.now().strftime('%Y%m%d')


def _find_sources_uses_link(html, page_url):
    """
    Find the PDF link for "Sources and Uses Table" on a press-release page.
    Handles various phrasings across different years.
    Returns the absolute URL or None.
    """
    soup = BeautifulSoup(html, 'html.parser')
    keywords = config.SOURCES_USES_LINK_KEYWORDS

    for a in soup.find_all('a', href=True):
        text = a.get_text(strip=True).lower()
        href = a['href'].strip()
        for kw in keywords:
            if kw.lower() in text:
                if href.startswith('http'):
                    return href
                return config.BASE_DOMAIN + href

    # Sometimes the link text says just "here" but is inside a div that says
    # "View the Sources and Uses" — search parent text
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        # Check if href itself looks like a sources-and-uses PDF
        if 'sources' in href.lower() and 'uses' in href.lower() and href.endswith('.pdf'):
            if href.startswith('http'):
                return href
            return config.BASE_DOMAIN + href

    return None


# ══════════════════════════════════════════════════════════════════════════════
# Strategy 1: requests + BeautifulSoup (no JS, fastest)
# ══════════════════════════════════════════════════════════════════════════════

def _requests_session():
    """Create a requests session that mimics a real browser."""
    session = requests.Session()
    session.headers.update({
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/125.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
    })
    return session


def _download_pdf_requests(pdf_url, dest_dir):
    """Download a PDF via requests and save to dest_dir. Returns path."""
    filename = pdf_url.rstrip('/').split('/')[-1]
    if not filename.endswith('.pdf'):
        filename = 'sources_uses.pdf'
    dest_path = os.path.join(dest_dir, filename)

    session = _requests_session()
    resp = session.get(pdf_url, timeout=60, stream=True)
    resp.raise_for_status()
    with open(dest_path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info(f"PDF downloaded via requests -> {dest_path}")
    return dest_path


def try_direct_download():
    """
    Attempt the full pipeline via requests + BeautifulSoup.
    Returns result dict on success, None on failure.
    """
    try:
        session = _requests_session()
        logger.info(f"[direct] Fetching archive page: {config.ARCHIVE_URL}")
        resp = session.get(config.ARCHIVE_URL, timeout=30)
        resp.raise_for_status()

        available = _parse_archive_html(resp.text)
        if not available:
            logger.warning("[direct] No quarter data parsed from archive page.")
            return None

        year, quarter, press_url = _select_target(available)
        logger.info(f"[direct] Target: {year} Q{quarter} -> {press_url}")

        # Handle legacy PDF-direct links (e.g. 2015 Q3 links directly to a PDF)
        if press_url.endswith('.pdf'):
            logger.info("[direct] Quarter link is a direct PDF — handling as legacy.")
            return _handle_legacy_pdf_link(press_url, year, quarter, session)

        logger.info(f"[direct] Fetching press-release page: {press_url}")
        resp2 = session.get(press_url, timeout=30)
        resp2.raise_for_status()

        date_str = _extract_page_date(resp2.text)
        pdf_url = _find_sources_uses_link(resp2.text, press_url)

        if not pdf_url:
            logger.warning("[direct] 'Sources and Uses Table' link not found on press-release page.")
            return None

        run_dir = _make_run_dir(year, quarter)
        pdf_path = _download_pdf_requests(pdf_url, run_dir)
        period_label = f"{config.QUARTER_PERIOD_LABEL[quarter]} {year}"

        return {
            'pdf_path':     pdf_path,
            'year':         year,
            'quarter':      quarter,
            'date_str':     date_str,
            'period_label': period_label,
        }

    except Exception as e:
        logger.warning(f"[direct] Strategy failed: {e}")
        return None


def _handle_legacy_pdf_link(pdf_url, year, quarter, session):
    """
    For quarters where the archive link IS the PDF (e.g. 2015 Q3).
    These PDFs are the financing-estimates tables (not Sources and Uses).
    We look inside the PDF for embedded links, or try to find the Sources
    and Uses PDF on the associated page. As a fallback, we download this PDF.
    """
    run_dir = _make_run_dir(year, quarter)
    pdf_path = _download_pdf_requests(pdf_url, run_dir)
    date_str = datetime.now().strftime('%Y%m%d')
    period_label = f"{config.QUARTER_PERIOD_LABEL[quarter]} {year}"
    return {
        'pdf_path':     pdf_path,
        'year':         year,
        'quarter':      quarter,
        'date_str':     date_str,
        'period_label': period_label,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Strategy 2: Selenium stealth (fallback for JS-protected pages)
# ══════════════════════════════════════════════════════════════════════════════

def _build_selenium_driver():
    """Build an undetected-chromedriver with selenium-stealth options."""
    import undetected_chromedriver as uc
    from selenium_stealth import stealth
    import random

    options = uc.ChromeOptions()

    if config.HEADLESS_MODE:
        options.add_argument('--headless=new')

    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--window-size=1920,1080')
    options.add_argument(
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/125.0.0.0 Safari/537.36'
    )

    driver = uc.Chrome(options=options, use_subprocess=True)
    stealth(
        driver,
        languages=['en-US', 'en'],
        vendor='Google Inc.',
        platform='Win32',
        webgl_vendor='Intel Inc.',
        renderer='Intel Iris OpenGL Engine',
        fix_hairline=True,
    )
    return driver


def _selenium_human_delay(driver, low=0.5, high=1.5):
    """Short human-like pause."""
    import random
    time.sleep(random.uniform(low, high))


def try_selenium_download():
    """
    Attempt the full pipeline via Selenium stealth.
    Returns result dict on success, None on failure.
    """
    driver = None
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        driver = _build_selenium_driver()
        wait = WebDriverWait(driver, config.WAIT_TIMEOUT)

        logger.info(f"[selenium] Navigating to archive page: {config.ARCHIVE_URL}")
        driver.get(config.ARCHIVE_URL)
        _selenium_human_delay(driver)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, 'table')))

        html = driver.page_source
        available = _parse_archive_html(html)
        if not available:
            logger.warning("[selenium] No quarter data parsed from archive page.")
            return None

        year, quarter, press_url = _select_target(available)
        logger.info(f"[selenium] Target: {year} Q{quarter} -> {press_url}")

        # Handle legacy PDF direct links
        if press_url.endswith('.pdf'):
            logger.info("[selenium] Quarter link is a direct PDF — handling as legacy.")
            driver.quit()
            session = _requests_session()
            return _handle_legacy_pdf_link(press_url, year, quarter, session)

        # Click the quarter link (human-like)
        try:
            link_el = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, f'a[href*="{press_url.split(config.BASE_DOMAIN)[-1]}"]')))
            _selenium_human_delay(driver)
            link_el.click()
        except Exception:
            driver.get(press_url)

        _selenium_human_delay(driver, 1.5, 3.0)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, 'body')))

        html2 = driver.page_source
        date_str = _extract_page_date(html2)
        pdf_url = _find_sources_uses_link(html2, driver.current_url)

        if not pdf_url:
            logger.warning("[selenium] 'Sources and Uses Table' link not found.")
            return None

        run_dir = _make_run_dir(year, quarter)
        # Download PDF via requests (more reliable than browser download)
        pdf_path = _download_pdf_requests(pdf_url, run_dir)
        period_label = f"{config.QUARTER_PERIOD_LABEL[quarter]} {year}"

        return {
            'pdf_path':     pdf_path,
            'year':         year,
            'quarter':      quarter,
            'date_str':     date_str,
            'period_label': period_label,
        }

    except Exception as e:
        logger.warning(f"[selenium] Strategy failed: {e}")
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def download():
    """
    Run the download pipeline. Tries direct requests first, then Selenium.
    Returns result dict or raises RuntimeError.
    """
    os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)

    logger.info("Trying direct download (requests + BeautifulSoup)...")
    result = try_direct_download()
    if result:
        return result

    logger.info("Trying Selenium stealth fallback...")
    result = try_selenium_download()
    if result:
        return result

    raise RuntimeError("All download strategies failed. Check the site or your network.")
