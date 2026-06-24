"""
scraper.py — Download the Sources and Uses Table PDF for SOMARQD.

Strategy:
  1. Try Selenium stealth (primary - mimics human clicks and triggers native downloads).
     Uses a single browser session to fetch target calendar list and click downloads.
  2. Fall back to direct requests + BeautifulSoup (backup).

The scraper:
  1. Loads the archive page to find quarterly links (determines year+quarter).
  2. Clicks (or follows) the quarter press-release link.
  3. On the press-release page, finds the "Sources and Uses Table" PDF link.
  4. Downloads the PDF to downloads/<timestamp>/<year>/Q<quarter>/

Returns a list of dicts, each like:
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
import logging
import subprocess
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import urllib3

import config

logger = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── quarter ordering: Q4=highest priority descending ──────────────────
QUARTER_ORDER = [4, 3, 2, 1]

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/125.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Connection': 'keep-alive',
}


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
            return int(ver.split('.')[0])
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
            return int(ver.split('.')[0])
        except Exception:
            pass

    # Linux / Docker
    for cmd in ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser']:
        try:
            out = subprocess.check_output(
                [cmd, '--version'], stderr=subprocess.DEVNULL
            ).decode()
            return int(out.strip().split()[-1].split('.')[0])
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
    quarters_by_name = {
        '4th quarter': 4,
        '3rd quarter': 3,
        '2nd quarter': 2,
        '1st quarter': 1,
    }

    result = {}
    current_year = None

    table = soup.find('table')
    if not table:
        return result

    for tr in table.find_all('tr'):
        ths = tr.find_all('th')
        if not ths:
            continue

        if len(ths) == 1:
            th = ths[0]
            year_id = th.get('id', '')
            if re.match(r'^\d{4}$', year_id.strip()):
                current_year = int(year_id.strip())
                result[current_year] = {}
            continue

        if current_year is not None and len(ths) == 4:
            for th in ths:
                text = th.get_text(strip=True).lower()
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
                    result[current_year][qnum] = None

    return result


def _get_targets(available):
    """
    Given the available dictionary, determine the list of (year, quarter, url) targets
    based on config.TARGET_YEAR and config.TARGET_QUARTER.
    """
    target_year = config.TARGET_YEAR
    target_quarter = config.TARGET_QUARTER

    targets = []

    if target_year is None:
        for year in sorted(available.keys(), reverse=True):
            quarters = available[year]
            for q in QUARTER_ORDER:
                if quarters.get(q) is not None:
                    targets.append((year, q, quarters[q]))
                    logger.info(f"Auto-detected latest target: {year} Q{q} -> {quarters[q]}")
                    return targets
        raise RuntimeError("No available quarter links found on the archive page.")

    if target_year not in available:
        raise RuntimeError(f"Year {target_year} not found on the archive page.")

    quarters = available[target_year]

    if target_quarter is not None:
        url = quarters.get(target_quarter)
        if url is None:
            raise RuntimeError(f"Quarter {target_quarter} for year {target_year} is not yet available.")
        targets.append((target_year, target_quarter, url))
        return targets

    for q in QUARTER_ORDER:
        if quarters.get(q) is not None:
            targets.append((target_year, q, quarters[q]))

    if not targets:
        raise RuntimeError(f"No available quarter links found for year {target_year}.")

    targets.sort(key=lambda t: t[1])
    logger.info(f"Selected targets for year {target_year}: {[(t[0], t[1]) for t in targets]}")
    return targets


def _extract_page_date(html):
    """Extract publication date from press-release page HTML."""
    soup = BeautifulSoup(html, 'html.parser')

    time_el = None
    pub_div = soup.find(class_='field--name-field-news-publication-date')
    if pub_div:
        time_el = pub_div.find('time', {'datetime': True})
    
    if not time_el:
        for el in soup.find_all('time', {'datetime': True}):
            parent_classes = el.parent.get('class', []) if el.parent else []
            if 'mm-news-row' not in parent_classes:
                time_el = el
                break

    if not time_el:
        time_el = soup.find('time', {'datetime': True})

    if time_el:
        dt_str = time_el['datetime']
        m = re.match(r'(\d{4})-(\d{2})-(\d{2})', dt_str)
        if m:
            return f"{m.group(1)}{m.group(2)}{m.group(3)}"

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
    """Find the PDF link for 'Sources and Uses Table' on a press-release page."""
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

    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        if 'sources' in href.lower() and 'uses' in href.lower() and href.endswith('.pdf'):
            if href.startswith('http'):
                return href
            return config.BASE_DOMAIN + href

    return None


# ══════════════════════════════════════════════════════════════════════════════
# Download helpers
# ══════════════════════════════════════════════════════════════════════════════

def _wait_for_download(download_dir, timeout=45):
    """Poll download_dir until a new .pdf file is fully written."""
    logger.info(f"Waiting for native PDF download in {download_dir}...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        files = os.listdir(download_dir)
        pdfs = [
            f for f in files
            if f.lower().endswith('.pdf') and not f.lower().endswith('.crdownload') and not f.lower().endswith('.tmp')
        ]
        if pdfs:
            path = os.path.join(download_dir, pdfs[0])
            try:
                initial_size = os.path.getsize(path)
                if initial_size > 5000:
                    time.sleep(1.5)
                    if os.path.exists(path) and os.path.getsize(path) == initial_size:
                        logger.info(f"Native download complete: {path} ({initial_size:,} bytes)")
                        return path
            except Exception:
                pass
        time.sleep(1)
    raise TimeoutError(f"PDF did not appear in '{download_dir}' within {timeout}s")


def _requests_session():
    """Create a requests session that mimics a real browser."""
    session = requests.Session()
    session.headers.update(_HEADERS)
    return session


def _download_pdf_via_requests(url, dest_path, cookies=None):
    """Download a PDF via requests. Returns True on success."""
    try:
        resp = requests.get(
            url,
            headers=_HEADERS,
            cookies=cookies or {},
            stream=True,
            timeout=120,
            verify=False,
        )
        resp.raise_for_status()
        content_type = resp.headers.get('Content-Type', '')
        if 'html' in content_type and 'pdf' not in content_type:
            logger.warning(f"Response is HTML, not PDF: {content_type}")
            return False

        with open(dest_path, 'wb') as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    fh.write(chunk)

        size = os.path.getsize(dest_path)
        if size < 50_000:
            logger.warning(f"Downloaded file suspiciously small: {size} bytes")
            return False

        logger.info(f"Downloaded {size:,} bytes -> {dest_path}")
        return True
    except Exception as exc:
        logger.warning(f"requests download failed: {exc}")
        return False


def _extract_link_from_wrapper_pdf(pdf_path):
    """Search annotations (/Annots) for embedded table links."""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        for page in doc:
            for link in page.get_links():
                if link.get('type') == fitz.LINK_URI:
                    uri = link.get('uri', '').strip()
                    if uri:
                        if uri.startswith('/'):
                            uri = config.BASE_DOMAIN + uri
                        doc.close()
                        return uri
        doc.close()
    except Exception as e:
        logger.warning(f"Failed to parse annotations from PDF {pdf_path}: {e}")
    return None


def _handle_legacy_pdf_link(pdf_url, year, quarter, session, cookies=None):
    """Handle quarters where the archive link is a wrapper PDF directly."""
    run_dir = _make_run_dir(year, quarter)
    filename = pdf_url.rstrip('/').split('/')[-1]
    if not filename.endswith('.pdf'):
        filename = 'legacy_wrapper.pdf'
    dest_path = os.path.join(run_dir, filename)

    if cookies:
        success = _download_pdf_via_requests(pdf_url, dest_path, cookies)
    else:
        s = session or _requests_session()
        try:
            resp = s.get(pdf_url, headers=_HEADERS, timeout=60, verify=False, stream=True)
            resp.raise_for_status()
            with open(dest_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
            success = os.path.getsize(dest_path) >= 50000
        except Exception:
            success = False

    if not success:
        raise RuntimeError(f"Failed to download legacy PDF from {pdf_url}")

    embedded_link = _extract_link_from_wrapper_pdf(dest_path)
    if embedded_link:
        logger.info(f"Found embedded link in legacy PDF: {embedded_link}. Downloading target PDF...")
        target_filename = embedded_link.rstrip('/').split('/')[-1]
        if not target_filename.endswith('.pdf'):
            target_filename = 'sources_uses.pdf'
        target_path = os.path.join(run_dir, target_filename)

        if cookies:
            success = _download_pdf_via_requests(embedded_link, target_path, cookies)
        else:
            s = session or _requests_session()
            try:
                resp = s.get(embedded_link, headers=_HEADERS, timeout=60, verify=False, stream=True)
                resp.raise_for_status()
                with open(target_path, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        f.write(chunk)
                success = os.path.getsize(target_path) >= 50000
            except Exception:
                success = False

        if success:
            try:
                os.remove(dest_path)
            except Exception:
                pass
            dest_path = target_path
            logger.info(f"Successfully replaced legacy wrapper with target table: {dest_path}")

    date_str = datetime.now().strftime('%Y%m%d')
    period_label = f"{config.QUARTER_PERIOD_LABEL[quarter]} {year}"
    return {
        'pdf_path':     dest_path,
        'year':         year,
        'quarter':      quarter,
        'date_str':     date_str,
        'period_label': period_label,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Browser Setup
# ══════════════════════════════════════════════════════════════════════════════

def _build_selenium_driver():
    """Build an undetected-chromedriver with stealth and download options."""
    import undetected_chromedriver as uc
    from selenium_stealth import stealth

    options = uc.ChromeOptions()

    if config.HEADLESS_MODE:
        options.add_argument('--headless=new')

    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--lang=en-US,en;q=0.9')

    options.add_experimental_option('prefs', {
        'download.prompt_for_download': False,
        'download.directory_upgrade': True,
        'plugins.always_open_pdf_externally': True,
        'safebrowsing.enabled': True,
    })

    chrome_version = _get_chrome_version()
    if chrome_version:
        try:
            logger.info(f"Initializing undetected_chromedriver with version_main={chrome_version}")
            driver = uc.Chrome(options=options, version_main=chrome_version, use_subprocess=True)
        except Exception as e:
            logger.warning(f"Failed to start uc.Chrome with version_main={chrome_version}: {e}. Retrying without version_main.")
            driver = uc.Chrome(options=options, use_subprocess=True)
    else:
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
    import random
    time.sleep(random.uniform(low, high))


# ══════════════════════════════════════════════════════════════════════════════
# Strategy 2: requests + BeautifulSoup (Backup Strategy)
# ══════════════════════════════════════════════════════════════════════════════

def try_direct_download(targets):
    """Backup: download list of resolved targets directly via requests."""
    results = []
    session = _requests_session()
    try:
        for year, quarter, press_url in targets:
            logger.info(f"[direct] Processing target: {year} Q{quarter} -> {press_url}")

            if press_url.endswith('.pdf'):
                logger.info("[direct] Target link is a direct PDF — handling as legacy.")
                res = _handle_legacy_pdf_link(press_url, year, quarter, session)
                results.append(res)
                continue

            logger.info(f"[direct] Fetching press-release page: {press_url}")
            resp = session.get(press_url, timeout=30)
            resp.raise_for_status()

            date_str = _extract_page_date(resp.text)
            pdf_url = _find_sources_uses_link(resp.text, press_url)

            if not pdf_url:
                logger.warning(f"[direct] 'Sources and Uses Table' link not found for {year} Q{quarter}.")
                return None

            run_dir = _make_run_dir(year, quarter)
            filename = pdf_url.rstrip('/').split('/')[-1]
            if not filename.endswith('.pdf'):
                filename = 'sources_uses.pdf'
            pdf_path = os.path.join(run_dir, filename)

            logger.info(f"[direct] Downloading PDF: {pdf_url}")
            if not _download_pdf_via_requests(pdf_url, pdf_path):
                logger.warning(f"[direct] Failed to download PDF for {year} Q{quarter}.")
                return None

            period_label = f"{config.QUARTER_PERIOD_LABEL[quarter]} {year}"
            results.append({
                'pdf_path':     pdf_path,
                'year':         year,
                'quarter':      quarter,
                'date_str':     date_str,
                'period_label': period_label,
            })
        return results
    except Exception as e:
        logger.warning(f"[direct] Backup strategy failed: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def download():
    """
    Run the download pipeline. Tries Selenium first (using a single browser session
    for target resolving + clicking), and uses requests + BeautifulSoup as backup.
    """
    os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)

    driver = None
    results = []

    logger.info("Trying Selenium stealth strategy (primary)...")
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        # 1. Initialize Selenium driver (Exactly ONCE)
        driver = _build_selenium_driver()
        wait = WebDriverWait(driver, config.WAIT_TIMEOUT)

        # 2. Fetch archive page
        logger.info(f"[selenium] Navigating to archive page: {config.ARCHIVE_URL}")
        driver.get(config.ARCHIVE_URL)
        _selenium_human_delay(driver, 1.5, 3.0)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, 'table')))

        # 3. Parse available quarters
        available = _parse_archive_html(driver.page_source)
        if not available:
            raise RuntimeError("No quarters parsed from archive page via Selenium.")

        # 4. Resolve targets
        targets = _get_targets(available)
        logger.info(f"[selenium] Targets resolved: {targets}")

        # 5. Process each target in the same browser session
        for year, quarter, press_url in targets:
            logger.info(f"[selenium] Processing target: {year} Q{quarter} -> {press_url}")

            # If we navigated away from the archive page, return to it
            if driver.current_url != config.ARCHIVE_URL:
                logger.info(f"[selenium] Returning to archive page: {config.ARCHIVE_URL}")
                driver.get(config.ARCHIVE_URL)
                _selenium_human_delay(driver, 1.0, 2.5)
                wait.until(EC.presence_of_element_located((By.TAG_NAME, 'table')))

            # Locate the cell under the year header using XPath
            th_cells = driver.find_elements(By.XPATH, f"//th[@headers='{year}']")
            target_cell = None
            quarter_name_map = {
                4: "4th",
                3: "3rd",
                2: "2nd",
                1: "1st",
            }
            target_q_label = quarter_name_map.get(quarter)
            
            for cell in th_cells:
                text = cell.text.lower().replace('\u200b', '').strip()
                if f"{target_q_label} quarter" in text:
                    target_cell = cell
                    break

            if not target_cell:
                raise RuntimeError(f"Could not find cell for {year} Q{quarter} on archive page.")

            # Find the link inside the cell
            try:
                link_el = target_cell.find_element(By.TAG_NAME, 'a')
            except Exception:
                raise RuntimeError(f"Quarter cell for {year} Q{quarter} does not contain a clickable link.")

            # Set up the download directory for this target via CDP
            run_dir = _make_run_dir(year, quarter)
            driver.execute_cdp_cmd(
                'Page.setDownloadBehavior',
                {'behavior': 'allow', 'downloadPath': run_dir},
            )

            # Mimic human action: scroll to the link cell and click via JS
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link_el)
            _selenium_human_delay(driver, 0.8, 1.8)
            driver.execute_script("arguments[0].click();", link_el)
            _selenium_human_delay(driver, 2.0, 4.0)

            # Check if we landed directly on a PDF
            current_url = driver.current_url
            if current_url.lower().endswith('.pdf') or press_url.lower().endswith('.pdf'):
                logger.info(f"[selenium] Direct PDF link triggered: {current_url or press_url}")
                try:
                    pdf_path = _wait_for_download(run_dir)
                except Exception as e:
                    logger.warning(f"[selenium] Native PDF download failed: {e}. Falling back to requests with cookies...")
                    filename = (current_url or press_url).rstrip('/').split('/')[-1]
                    if not filename.endswith('.pdf'):
                        filename = 'legacy_wrapper.pdf'
                    pdf_path = os.path.join(run_dir, filename)
                    cookies = {c['name']: c['value'] for c in driver.get_cookies()}
                    if not _download_pdf_via_requests(current_url or press_url, pdf_path, cookies):
                        raise RuntimeError("Failed to download PDF wrapper via requests fallback.")

                # Handle legacy PDF wrapper check
                embedded_link = _extract_link_from_wrapper_pdf(pdf_path)
                if embedded_link:
                    logger.info(f"[selenium] Found embedded link in legacy PDF: {embedded_link}. Triggering download...")
                    driver.execute_cdp_cmd(
                        'Page.setDownloadBehavior',
                        {'behavior': 'allow', 'downloadPath': run_dir},
                    )
                    driver.get(embedded_link)
                    _selenium_human_delay(driver, 2.0, 4.0)
                    
                    try:
                        actual_pdf_path = _wait_for_download(run_dir)
                        try:
                            os.remove(pdf_path)
                        except Exception:
                            pass
                        pdf_path = actual_pdf_path
                    except Exception as e:
                        logger.warning(f"[selenium] Native download of embedded PDF failed: {e}. Falling back to requests...")
                        target_filename = embedded_link.rstrip('/').split('/')[-1]
                        if not target_filename.endswith('.pdf'):
                            target_filename = 'sources_uses.pdf'
                        target_path = os.path.join(run_dir, target_filename)
                        cookies = {c['name']: c['value'] for c in driver.get_cookies()}
                        if _download_pdf_via_requests(embedded_link, target_path, cookies):
                            try:
                                os.remove(pdf_path)
                            except Exception:
                                pass
                            pdf_path = target_path
                        else:
                            raise RuntimeError("Failed to download actual PDF via requests fallback.")

                date_str = datetime.now().strftime('%Y%m%d')
                period_label = f"{config.QUARTER_PERIOD_LABEL[quarter]} {year}"
                results.append({
                    'pdf_path':     pdf_path,
                    'year':         year,
                    'quarter':      quarter,
                    'date_str':     date_str,
                    'period_label': period_label,
                })
                continue

            # Press-release page
            wait.until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
            html2 = driver.page_source

            date_str = _extract_page_date(html2)
            pdf_url = _find_sources_uses_link(html2, driver.current_url)

            if not pdf_url:
                raise RuntimeError(f"'Sources and Uses Table' link not found for {year} Q{quarter}.")

            # Try native browser click on PDF link
            pdf_link_el = None
            for kw in config.SOURCES_USES_LINK_KEYWORDS:
                try:
                    pdf_link_el = driver.find_element(By.XPATH, f"//a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{kw.lower()}')]")
                    break
                except Exception:
                    continue
            
            if not pdf_link_el:
                try:
                    pdf_link_el = driver.find_element(By.XPATH, "//a[contains(@href, '.pdf') and (contains(@href, 'sources') or contains(@href, 'Sources'))]")
                except Exception:
                    pass

            download_success = False
            pdf_path = None
            
            if pdf_link_el:
                logger.info(f"[selenium] Clicking PDF link natively: {pdf_link_el.text}")
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", pdf_link_el)
                _selenium_human_delay(driver, 0.8, 1.8)
                driver.execute_script("arguments[0].click();", pdf_link_el)
                _selenium_human_delay(driver, 2.0, 4.0)
                
                try:
                    pdf_path = _wait_for_download(run_dir)
                    download_success = True
                except Exception as e:
                    logger.warning(f"[selenium] Native PDF download from link failed: {e}. Falling back to requests...")

            if not download_success:
                # Request-based fallback using browser cookies
                filename = pdf_url.rstrip('/').split('/')[-1]
                if not filename.endswith('.pdf'):
                    filename = 'sources_uses.pdf'
                pdf_path = os.path.join(run_dir, filename)

                cookies = {c['name']: c['value'] for c in driver.get_cookies()}
                logger.info(f"[selenium] Downloading PDF via requests fallback: {pdf_url}")
                if not _download_pdf_via_requests(pdf_url, pdf_path, cookies):
                    raise RuntimeError(f"Failed to download PDF fallback for {year} Q{quarter}.")

            period_label = f"{config.QUARTER_PERIOD_LABEL[quarter]} {year}"
            results.append({
                'pdf_path':     pdf_path,
                'year':         year,
                'quarter':      quarter,
                'date_str':     date_str,
                'period_label': period_label,
            })

        # Return successfully collected results
        return results

    except Exception as e:
        logger.warning(f"Selenium strategy failed or timed out: {e}")
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
            driver = None

        # ── Backup Strategy: Direct requests ─────────────────────────────────
        logger.info("Direct download strategy (backup) triggered...")
        try:
            session = _requests_session()
            logger.info(f"[backup] Fetching archive page: {config.ARCHIVE_URL}")
            resp = session.get(config.ARCHIVE_URL, timeout=30)
            resp.raise_for_status()
            available = _parse_archive_html(resp.text)
            if not available:
                raise RuntimeError("No quarters parsed from archive page via direct requests.")
            targets = _get_targets(available)
            return try_direct_download(targets)
        except Exception as err:
            logger.error(f"[backup] Direct download strategy failed: {err}")
            raise RuntimeError("All download strategies (Selenium and backup requests) failed.") from err

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
