"""
Shared scraping utilities — rate limiting, retry, HTML fetching.
"""
import os
import sys
import time
import random
import logging
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# Add repo root to path for engine imports
from lib.logging_config import get_logger

logger = get_logger("scrapers.utils")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def fetch_html(
    url: str,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    timeout: int = 30,
    user_agent: Optional[str] = None,
) -> Optional[str]:
    """Fetch HTML from a URL with retry and exponential backoff.

    Falls back to Playwright if requests are blocked (403/429).
    """
    ua = user_agent or DEFAULT_USER_AGENT

    for attempt in range(max_retries):
        try:
            req = Request(url, headers={"User-Agent": ua})
            with urlopen(req, timeout=timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                html = resp.read().decode(charset, errors="replace")
                if len(html) < 500 and ("captcha" in html.lower() or "blocked" in html.lower()):
                    logger.warning(f"Possible bot block on {url}, trying Playwright")
                    return _fetch_with_playwright(url, timeout)
                return html
        except HTTPError as e:
            if e.code in (403, 429):
                logger.warning(f"HTTP {e.code} on {url}, trying Playwright fallback")
                return _fetch_with_playwright(url, timeout)
            if attempt < max_retries - 1:
                wait = backoff_base ** attempt + random.uniform(0, 1)
                logger.warning(f"HTTP {e.code} fetching {url}, retry in {wait:.1f}s")
                time.sleep(wait)
            else:
                logger.error(f"Failed to fetch {url} after {max_retries} attempts: {e}")
                return None
        except (URLError, TimeoutError, OSError) as e:
            if attempt < max_retries - 1:
                wait = backoff_base ** attempt + random.uniform(0, 1)
                logger.warning(f"Error fetching {url}: {e}, retry in {wait:.1f}s")
                time.sleep(wait)
            else:
                logger.error(f"Failed to fetch {url} after {max_retries} attempts: {e}")
                return None
    return None


def _fetch_with_playwright(url: str, timeout: int = 30) -> Optional[str]:
    """Headless Chromium fallback for bot-protected pages."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error(
            "Playwright not installed. Run: pip install playwright && playwright install chromium"
        )
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        logger.error(f"Playwright fetch failed for {url}: {e}")
        return None


def rate_limit_sleep(min_seconds: float = 1.0, max_seconds: float = 3.0):
    """Random sleep to stay under rate limits."""
    time.sleep(random.uniform(min_seconds, max_seconds))


def ensure_data_dir(data_dir: str) -> str:
    """Create the data directory if it doesn't exist, return absolute path."""
    abs_path = os.path.abspath(data_dir)
    os.makedirs(abs_path, exist_ok=True)
    return abs_path


def atomic_write_json(filepath: str, data) -> None:
    """Write JSON atomically using temp file + rename."""
    import json
    import tempfile

    dir_path = os.path.dirname(filepath)
    os.makedirs(dir_path, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w", dir=dir_path, suffix=".tmp", delete=False
    ) as tmp:
        json.dump(data, tmp, indent=2, default=str)
        tmp_path = tmp.name

    os.replace(tmp_path, filepath)
    logger.info(f"Wrote {filepath}")


def load_json(filepath: str, default=None):
    """Load JSON from file, return default if not found."""
    import json
    if not os.path.exists(filepath):
        return default if default is not None else []
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to load {filepath}: {e}")
        return default if default is not None else []
