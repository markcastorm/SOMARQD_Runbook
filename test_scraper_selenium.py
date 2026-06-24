import logging
import sys
import traceback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

import scraper

try:
    print("Testing refactored scraper.download() (Selenium first, requests fallback)...")
    res = scraper.download()
    print("SUCCESS! Result:", res)
except Exception as e:
    print("FAILED with exception:")
    traceback.print_exc()
