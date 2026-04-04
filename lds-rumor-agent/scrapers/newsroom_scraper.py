#!/usr/bin/env python3
"""
Component 1: Ground Truth Scraper

Scrapes official Church announcements from:
  1. newsroom.churchofjesuschrist.org — press releases, news feed
  2. churchofjesuschrist.org/temples — temple status page

Produces the "answer key" — every official announcement over the lookback period.
Output: data/ground_truth.json
"""
import os
import sys
import re
import json
import hashlib
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any
from html.parser import HTMLParser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from engines.logging_config import get_logger

# Add lds-rumor-agent root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from models import AnnouncementRecord, AnnouncementCategory, Location
from scrapers.utils import fetch_html, rate_limit_sleep, atomic_write_json, load_json

logger = get_logger("scrapers.newsroom")


# ──────────────────────────────────────────────
# HTML Parsing Helpers
# ──────────────────────────────────────────────

class _NewsroomParser(HTMLParser):
    """Extract article links and metadata from newsroom listing pages."""

    def __init__(self):
        super().__init__()
        self.articles: List[Dict[str, str]] = []
        self._in_article = False
        self._current = {}
        self._capture_text = False
        self._text_target = None
        self._text_buf = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        # Detect article containers (newsroom uses article tags or divs with article classes)
        if tag == "article" or (tag == "div" and "article" in attrs_dict.get("class", "")):
            self._in_article = True
            self._current = {}

        # Links within articles
        if self._in_article and tag == "a" and "href" in attrs_dict:
            href = attrs_dict["href"]
            if "/article/" in href or "/announcement/" in href or "/press-release/" in href:
                self._current["url"] = href

        # Title elements
        if self._in_article and tag in ("h2", "h3"):
            self._capture_text = True
            self._text_target = "title"
            self._text_buf = []

        # Date/time elements
        if self._in_article and tag == "time" and "datetime" in attrs_dict:
            self._current["date"] = attrs_dict["datetime"]

        # Span with date class
        if self._in_article and tag == "span" and "date" in attrs_dict.get("class", ""):
            self._capture_text = True
            self._text_target = "date_text"
            self._text_buf = []

    def handle_endtag(self, tag):
        if self._capture_text and tag in ("h2", "h3", "span"):
            text = "".join(self._text_buf).strip()
            if self._text_target == "title" and text:
                self._current["title"] = text
            elif self._text_target == "date_text" and text:
                self._current.setdefault("date_text", text)
            self._capture_text = False
            self._text_target = None
            self._text_buf = []

        if tag == "article" or (tag == "div" and self._in_article):
            if self._current.get("url") or self._current.get("title"):
                self.articles.append(self._current)
            self._in_article = False
            self._current = {}

    def handle_data(self, data):
        if self._capture_text:
            self._text_buf.append(data)


class _ArticleParser(HTMLParser):
    """Extract content from an individual newsroom article page."""

    def __init__(self):
        super().__init__()
        self.title = ""
        self.date_str = ""
        self.paragraphs: List[str] = []
        self.tags: List[str] = []
        self._in_title = False
        self._in_content = False
        self._in_tag = False
        self._text_buf: List[str] = []
        self._tag_stack: List[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")

        if tag == "h1":
            self._in_title = True
            self._text_buf = []
        if tag == "time" and "datetime" in attrs_dict:
            self.date_str = attrs_dict["datetime"]
        if tag == "div" and ("body" in cls or "content" in cls or "article-body" in cls):
            self._in_content = True
        if self._in_content and tag == "p":
            self._text_buf = []
            self._tag_stack.append("p")
        if tag == "a" and "tag" in cls:
            self._in_tag = True
            self._text_buf = []

    def handle_endtag(self, tag):
        if tag == "h1" and self._in_title:
            self.title = "".join(self._text_buf).strip()
            self._in_title = False
        if tag == "p" and self._tag_stack and self._tag_stack[-1] == "p":
            text = "".join(self._text_buf).strip()
            if text:
                self.paragraphs.append(text)
            self._text_buf = []
            self._tag_stack.pop()
        if tag == "a" and self._in_tag:
            text = "".join(self._text_buf).strip()
            if text:
                self.tags.append(text.lower())
            self._in_tag = False

    def handle_data(self, data):
        if self._in_title or (self._tag_stack and self._tag_stack[-1] == "p") or self._in_tag:
            self._text_buf.append(data)


class _TempleListParser(HTMLParser):
    """Extract temple announcements from the temples status page."""

    def __init__(self):
        super().__init__()
        self.temples: List[Dict[str, str]] = []
        self._in_temple = False
        self._current: Dict[str, str] = {}
        self._capture = False
        self._text_buf: List[str] = []
        self._capture_target = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")

        # Temple list items
        if tag in ("li", "div", "tr") and ("temple" in cls.lower()):
            self._in_temple = True
            self._current = {}

        if self._in_temple:
            if tag == "a" and "href" in attrs_dict:
                self._current["url"] = attrs_dict["href"]
                self._capture = True
                self._capture_target = "name"
                self._text_buf = []
            if tag == "span" and ("status" in cls or "date" in cls or "location" in cls):
                self._capture = True
                self._capture_target = "status" if "status" in cls else "info"
                self._text_buf = []

    def handle_endtag(self, tag):
        if self._capture and tag in ("a", "span"):
            text = "".join(self._text_buf).strip()
            if text:
                self._current[self._capture_target] = text
            self._capture = False
            self._text_buf = []

        if tag in ("li", "div", "tr") and self._in_temple:
            if self._current.get("name"):
                self.temples.append(self._current)
            self._in_temple = False

    def handle_data(self, data):
        if self._capture:
            self._text_buf.append(data)


# ──────────────────────────────────────────────
# Category Detection
# ──────────────────────────────────────────────

_CATEGORY_PATTERNS = {
    AnnouncementCategory.TEMPLE_ANNOUNCEMENT: [
        r"temple", r"groundbreaking", r"dedication", r"rededication",
    ],
    AnnouncementCategory.POLICY_UPDATE: [
        r"handbook", r"policy", r"guideline", r"update to",
        r"revision", r"missionary.*rule",
    ],
    AnnouncementCategory.LEADERSHIP_CHANGE: [
        r"called as", r"appointed", r"released as", r"sustained",
        r"apostle", r"seventy", r"general authority", r"mission president",
        r"relief society", r"young (?:men|women)", r"primary president",
    ],
    AnnouncementCategory.ORGANIZATIONAL: [
        r"stake", r"ward.*boundar", r"reorganiz", r"new mission",
        r"area.*authorit", r"discontinu",
    ],
    AnnouncementCategory.PROGRAM: [
        r"curriculum", r"seminary", r"institute", r"fsy",
        r"justserve", r"come.?follow.?me",
    ],
    AnnouncementCategory.FINANCIAL: [
        r"tithing", r"financial", r"invest", r"audit",
        r"ensign peak", r"deseret",
    ],
    AnnouncementCategory.CULTURAL: [
        r"byu", r"disciplin", r"excommun", r"statement on",
        r"public statement",
    ],
}


def _classify_category(title: str, summary: str) -> AnnouncementCategory:
    """Classify an announcement by keyword matching."""
    text = f"{title} {summary}".lower()
    for category, patterns in _CATEGORY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text):
                return category
    return AnnouncementCategory.OTHER


def _detect_temple_subcategory(title: str, summary: str) -> Optional[str]:
    """Detect temple-specific subcategory."""
    text = f"{title} {summary}".lower()
    if "groundbreaking" in text:
        return "groundbreaking"
    if "rededication" in text or "rededicate" in text:
        return "rededication"
    if "dedication" in text or "dedicate" in text:
        return "dedication"
    if "renovation" in text or "remodel" in text:
        return "renovation"
    if "announced" in text or "new temple" in text:
        return "new_temple"
    return None


def _extract_location(title: str, summary: str) -> Optional[Location]:
    """Try to extract location from title/summary text."""
    text = f"{title} {summary}"
    # Common pattern: "Temple in City, State/Country"
    match = re.search(r"(?:temple|church)\s+in\s+([^,.\n]+?)(?:,\s*([^,.\n]+?))?(?:\.|,|\s+(?:during|will))", text, re.IGNORECASE)
    if match:
        city = match.group(1).strip()
        region = match.group(2).strip() if match.group(2) else None
        return Location(city=city, state=region)
    return None


def _generate_id(prefix: str, title: str, date_str: str) -> str:
    """Generate a deterministic ID from content."""
    content = f"{title}:{date_str}"
    hash_part = hashlib.md5(content.encode()).hexdigest()[:6]
    return f"{prefix}-{hash_part}"


# ──────────────────────────────────────────────
# Scraping Functions
# ──────────────────────────────────────────────

def scrape_newsroom(
    base_url: str = "https://newsroom.churchofjesuschrist.org",
    lookback_months: int = 12,
    max_pages: int = 50,
) -> List[AnnouncementRecord]:
    """Scrape the Church newsroom for official announcements."""
    cutoff = date.today() - timedelta(days=lookback_months * 30)
    announcements = []
    seen_urls = set()

    # Try multiple listing endpoints
    listing_paths = [
        "/articles",
        "/announcements",
        "/press-releases",
        "/topic/general-conference",
        "/topic/temples",
        "/topic/leadership-changes",
    ]

    for path in listing_paths:
        logger.info(f"Scraping {base_url}{path}")
        page = 1

        while page <= max_pages:
            url = f"{base_url}{path}?page={page}" if page > 1 else f"{base_url}{path}"
            html = fetch_html(url)
            if not html:
                break

            parser = _NewsroomParser()
            try:
                parser.feed(html)
            except Exception as e:
                logger.warning(f"Parse error on {url}: {e}")
                break

            if not parser.articles:
                break

            hit_cutoff = False
            for article in parser.articles:
                article_url = article.get("url", "")
                if not article_url:
                    continue
                if not article_url.startswith("http"):
                    article_url = f"{base_url}{article_url}"
                if article_url in seen_urls:
                    continue
                seen_urls.add(article_url)

                # Parse date
                article_date = _parse_date(article.get("date") or article.get("date_text"))
                if article_date and article_date < cutoff:
                    hit_cutoff = True
                    continue

                # Fetch full article
                record = _scrape_article(article_url, article.get("title"), article_date)
                if record:
                    announcements.append(record)
                rate_limit_sleep(1.0, 2.5)

            if hit_cutoff or len(parser.articles) < 5:
                break
            page += 1
            rate_limit_sleep(2.0, 4.0)

    logger.info(f"Scraped {len(announcements)} newsroom announcements")
    return announcements


def _scrape_article(
    url: str,
    fallback_title: Optional[str] = None,
    fallback_date: Optional[date] = None,
) -> Optional[AnnouncementRecord]:
    """Fetch and parse a single newsroom article."""
    html = fetch_html(url)
    if not html:
        return None

    parser = _ArticleParser()
    try:
        parser.feed(html)
    except Exception as e:
        logger.warning(f"Parse error on article {url}: {e}")
        return None

    title = parser.title or fallback_title or ""
    if not title:
        return None

    article_date = _parse_date(parser.date_str) or fallback_date or date.today()
    summary = " ".join(parser.paragraphs[:3])[:500] if parser.paragraphs else title

    category = _classify_category(title, summary)
    subcategory = _detect_temple_subcategory(title, summary) if category == AnnouncementCategory.TEMPLE_ANNOUNCEMENT else None
    location = _extract_location(title, summary)

    return AnnouncementRecord(
        id=_generate_id("ann", title, str(article_date)),
        date=article_date,
        category=category,
        title=title,
        summary=summary,
        source_url=url,
        subcategory=subcategory,
        location=location,
        tags=parser.tags or [],
    )


def scrape_temples(
    temples_url: str = "https://www.churchofjesuschrist.org/temples",
) -> List[AnnouncementRecord]:
    """Scrape the temple status page for temple announcements with dates."""
    logger.info(f"Scraping temple status from {temples_url}")
    html = fetch_html(temples_url)
    if not html:
        return []

    parser = _TempleListParser()
    try:
        parser.feed(html)
    except Exception as e:
        logger.warning(f"Parse error on temples page: {e}")
        return []

    announcements = []
    for temple in parser.temples:
        name = temple.get("name", "")
        status = temple.get("status", "")
        if not name:
            continue

        # Try to determine category and date from status
        subcategory = None
        if "announced" in status.lower():
            subcategory = "new_temple"
        elif "ground" in status.lower():
            subcategory = "groundbreaking"
        elif "dedicat" in status.lower():
            subcategory = "dedication"

        temple_date = _parse_date(temple.get("info")) or date.today()

        record = AnnouncementRecord(
            id=_generate_id("ann", f"temple-{name}", str(temple_date)),
            date=temple_date,
            category=AnnouncementCategory.TEMPLE_ANNOUNCEMENT,
            title=f"{name} Temple — {status}" if status else f"{name} Temple",
            summary=f"Temple status: {status}" if status else name,
            source_url=temple.get("url", temples_url),
            subcategory=subcategory,
            location=_parse_temple_location(name),
            tags=["temple"],
        )
        announcements.append(record)

    logger.info(f"Scraped {len(announcements)} temple records")
    return announcements


def _parse_temple_location(name: str) -> Optional[Location]:
    """Parse location from temple name (e.g., 'Nuku'alofa Tonga')."""
    parts = name.strip().split()
    if len(parts) >= 2:
        return Location(city=parts[0], country=parts[-1])
    return Location(city=name)


def _parse_date(date_str: Optional[str]) -> Optional[date]:
    """Parse various date formats."""
    if not date_str:
        return None
    date_str = date_str.strip()

    formats = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
        "%m/%d/%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str[:len(date_str)], fmt).date()
        except ValueError:
            continue

    # Try to extract date from freeform text
    match = re.search(
        r"(\w+ \d{1,2},?\s*\d{4})|(\d{4}-\d{2}-\d{2})|(\d{1,2}/\d{1,2}/\d{4})",
        date_str,
    )
    if match:
        return _parse_date(match.group(0))
    return None


# ──────────────────────────────────────────────
# Deduplication
# ──────────────────────────────────────────────

def deduplicate_announcements(records: List[AnnouncementRecord]) -> List[AnnouncementRecord]:
    """Remove duplicate announcements (same event from different sources)."""
    seen = {}
    for record in records:
        # Key by normalized title + date (within 3-day window)
        norm_title = re.sub(r"[^a-z0-9]", "", record.title.lower())
        key = f"{norm_title}:{record.date.isoformat()[:7]}"

        if key not in seen:
            seen[key] = record
        else:
            # Keep the one with more info
            existing = seen[key]
            if len(record.summary) > len(existing.summary):
                seen[key] = record

    deduped = list(seen.values())
    logger.info(f"Deduplicated {len(records)} -> {len(deduped)} announcements")
    return deduped


# ──────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────

def scrape_ground_truth(
    newsroom_url: str = "https://newsroom.churchofjesuschrist.org",
    temples_url: str = "https://www.churchofjesuschrist.org/temples",
    lookback_months: int = 12,
    output_path: Optional[str] = None,
) -> List[AnnouncementRecord]:
    """Full ground truth scraping pipeline."""
    logger.info(f"Starting ground truth scrape (lookback={lookback_months} months)")

    newsroom_records = scrape_newsroom(newsroom_url, lookback_months)
    temple_records = scrape_temples(temples_url)

    all_records = newsroom_records + temple_records
    deduped = deduplicate_announcements(all_records)

    # Sort by date descending
    deduped.sort(key=lambda r: r.date, reverse=True)

    if output_path:
        atomic_write_json(output_path, [r.model_dump(mode="json") for r in deduped])

    logger.info(f"Ground truth complete: {len(deduped)} announcements")
    return deduped


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scrape LDS Church ground truth announcements")
    parser.add_argument("--output", default="data/ground_truth.json")
    parser.add_argument("--lookback", type=int, default=12, help="Months to look back")
    parser.add_argument("--newsroom-url", default="https://newsroom.churchofjesuschrist.org")
    parser.add_argument("--temples-url", default="https://www.churchofjesuschrist.org/temples")
    args = parser.parse_args()

    from engines.logging_config import setup_logging
    setup_logging("INFO")

    results = scrape_ground_truth(
        newsroom_url=args.newsroom_url,
        temples_url=args.temples_url,
        lookback_months=args.lookback,
        output_path=args.output,
    )
    print(f"Scraped {len(results)} announcements -> {args.output}")
