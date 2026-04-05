#!/usr/bin/env python3
"""
Church Website Change Detection System

Monitors official Church websites for changes that may signal upcoming
announcements or corroborate existing rumors.

Two detection modes:
  1. Sitemap diffing — detect newly added URLs in Church sitemaps
  2. Page content diffing — snapshot key pages, detect structural/content changes

Changes feed into the Bayesian model as:
  - Corroborating evidence for existing rumor clusters (boosted score)
  - Standalone signals when no matching rumor exists (generates rumor-like records)
"""
import os
import sys
import re
import hashlib
import difflib
from datetime import date, datetime
from typing import List, Dict, Any, Optional, Tuple, Set
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from engines.logging_config import get_logger

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from models import (
    SiteChangeRecord, SiteChangeType, SiteChangeSignificance,
    AnnouncementCategory, MonitoredPage,
)
from scrapers.utils import fetch_html, rate_limit_sleep, atomic_write_json, load_json

logger = get_logger("scrapers.church_site_monitor")

# Namespace for sitemap XML
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


# ──────────────────────────────────────────────
# Text Extraction (for content diffing)
# ──────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    """Extract visible text from HTML, stripping scripts/styles."""

    def __init__(self):
        super().__init__()
        self._skip_tags = {"script", "style", "noscript", "svg", "path"}
        self._skip_depth = 0
        self.text_parts: List[str] = []
        self.links: List[str] = []
        self.headings: List[str] = []
        self._in_heading = False
        self._heading_buf: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip_depth += 1
        attrs_dict = dict(attrs)
        if tag == "a" and "href" in attrs_dict:
            self.links.append(attrs_dict["href"])
        if tag in ("h1", "h2", "h3", "h4"):
            self._in_heading = True
            self._heading_buf = []

    def handle_endtag(self, tag):
        if tag in self._skip_tags and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in ("h1", "h2", "h3", "h4") and self._in_heading:
            heading = " ".join(self._heading_buf).strip()
            if heading:
                self.headings.append(heading)
            self._in_heading = False

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        text = data.strip()
        if text:
            self.text_parts.append(text)
            if self._in_heading:
                self._heading_buf.append(text)

    def get_text(self) -> str:
        return "\n".join(self.text_parts)


def _extract_text(html: str) -> Tuple[str, List[str], List[str]]:
    """Extract visible text, links, and headings from HTML."""
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
    except Exception:
        pass
    return extractor.get_text(), extractor.links, extractor.headings


def _content_hash(text: str) -> str:
    """Hash normalized text content for change detection."""
    normalized = re.sub(r"\s+", " ", text.lower().strip())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


# ──────────────────────────────────────────────
# Sitemap Diffing
# ──────────────────────────────────────────────

def fetch_sitemap_urls(sitemap_url: str) -> Set[str]:
    """Fetch and parse a sitemap XML, return all URLs.

    Handles sitemap index files (sitemaps of sitemaps).
    """
    urls: Set[str] = set()
    html = fetch_html(sitemap_url)
    if not html:
        return urls

    try:
        root = ET.fromstring(html)
    except ET.ParseError as e:
        logger.warning(f"Failed to parse sitemap {sitemap_url}: {e}")
        return urls

    # Check if this is a sitemap index
    sitemapindex_tag = f"{{{SITEMAP_NS['sm']}}}sitemapindex"
    sitemap_tag = f"{{{SITEMAP_NS['sm']}}}sitemap"
    urlset_tag = f"{{{SITEMAP_NS['sm']}}}urlset"
    url_tag = f"{{{SITEMAP_NS['sm']}}}url"
    loc_tag = f"{{{SITEMAP_NS['sm']}}}loc"

    if root.tag == sitemapindex_tag or root.tag == "sitemapindex":
        # Sitemap index — recurse into child sitemaps
        for sitemap in root.findall(f".//{sitemap_tag}") or root.findall(".//sitemap"):
            loc = sitemap.find(loc_tag) or sitemap.find("loc")
            if loc is not None and loc.text:
                child_url = loc.text.strip()
                # Only follow Church-domain sitemaps
                if "churchofjesuschrist.org" in child_url:
                    logger.debug(f"Following child sitemap: {child_url}")
                    child_urls = fetch_sitemap_urls(child_url)
                    urls.update(child_urls)
                    rate_limit_sleep(0.5, 1.0)
    else:
        # Regular sitemap — extract URLs
        for url_elem in root.findall(f".//{url_tag}") or root.findall(".//url"):
            loc = url_elem.find(loc_tag) or url_elem.find("loc")
            if loc is not None and loc.text:
                urls.add(loc.text.strip())

    logger.info(f"Sitemap {sitemap_url}: {len(urls)} URLs")
    return urls


def diff_sitemaps(
    current_urls: Set[str],
    previous_urls: Set[str],
) -> Tuple[Set[str], Set[str]]:
    """Compare two sitemap snapshots.

    Returns:
        (new_urls, removed_urls)
    """
    new_urls = current_urls - previous_urls
    removed_urls = previous_urls - current_urls
    return new_urls, removed_urls


def _classify_url(url: str) -> Optional[AnnouncementCategory]:
    """Classify a Church URL into an announcement category."""
    url_lower = url.lower()
    if "/temples" in url_lower or "/temple" in url_lower:
        return AnnouncementCategory.TEMPLE_ANNOUNCEMENT
    if "/callings" in url_lower or "/leader" in url_lower:
        return AnnouncementCategory.LEADERSHIP_CHANGE
    if "handbook" in url_lower or "/policy" in url_lower:
        return AnnouncementCategory.POLICY_UPDATE
    if "/stake" in url_lower or "/ward" in url_lower or "/mission" in url_lower:
        return AnnouncementCategory.ORGANIZATIONAL
    if "/seminary" in url_lower or "/institute" in url_lower or "/youth" in url_lower:
        return AnnouncementCategory.PROGRAM
    if "/come-follow-me" in url_lower or "/curriculum" in url_lower:
        return AnnouncementCategory.PROGRAM
    if "/byu" in url_lower:
        return AnnouncementCategory.CULTURAL
    if "store." in url_lower or "/store" in url_lower:
        return AnnouncementCategory.PROGRAM
    if "/finances" in url_lower or "/tithing" in url_lower:
        return AnnouncementCategory.FINANCIAL
    return None


def _url_significance(url: str) -> SiteChangeSignificance:
    """Estimate significance of a new URL."""
    url_lower = url.lower()
    # High: temple pages, handbook sections, leadership
    if any(k in url_lower for k in ["/temples/", "/handbook/", "/apostle", "/prophet"]):
        return SiteChangeSignificance.HIGH
    # Medium: organizational, program
    if any(k in url_lower for k in ["/callings/", "/stake", "/mission", "/curriculum"]):
        return SiteChangeSignificance.MEDIUM
    return SiteChangeSignificance.LOW


def _generate_change_id(url: str, change_type: str) -> str:
    """Generate a deterministic change ID."""
    content = f"{url}:{change_type}:{date.today().isoformat()}"
    hash_part = hashlib.md5(content.encode()).hexdigest()[:6]
    return f"site-{date.today().year}-{hash_part}"


# ──────────────────────────────────────────────
# Page Content Diffing
# ──────────────────────────────────────────────

def snapshot_page(
    url: str,
    snapshot_dir: str,
    label: str = "",
) -> Tuple[str, str, List[str], List[str]]:
    """Fetch a page and save a text snapshot.

    Returns:
        (text_content, content_hash, links, headings)
    """
    html = fetch_html(url)
    if not html:
        return "", "", [], []

    text, links, headings = _extract_text(html)
    content_hash = _content_hash(text)

    # Save snapshot
    os.makedirs(snapshot_dir, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9]", "_", url)[:80]
    snapshot_path = os.path.join(snapshot_dir, f"{safe_name}.txt")
    with open(snapshot_path, "w") as f:
        f.write(text)

    return text, content_hash, links, headings


def diff_page_content(
    current_text: str,
    previous_text: str,
    context_lines: int = 3,
) -> Tuple[List[str], float]:
    """Diff two page snapshots, return changed lines and change ratio.

    Returns:
        (diff_lines, change_ratio)
    """
    current_lines = current_text.splitlines()
    previous_lines = previous_text.splitlines()

    differ = difflib.unified_diff(
        previous_lines, current_lines,
        fromfile="previous", tofile="current",
        n=context_lines, lineterm="",
    )
    diff_lines = list(differ)

    # Calculate change ratio
    if not previous_lines:
        return diff_lines, 1.0

    # Count added + removed lines
    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    change_ratio = (added + removed) / max(len(previous_lines), 1)

    return diff_lines, min(change_ratio, 1.0)


def _diff_significance(change_ratio: float, diff_lines: List[str]) -> SiteChangeSignificance:
    """Determine significance of a page content change."""
    # Check for keyword-heavy changes
    diff_text = " ".join(diff_lines).lower()
    high_signal_keywords = [
        "temple", "announced", "new", "leadership", "handbook",
        "policy", "missionary", "president", "apostle", "conference",
    ]
    keyword_hits = sum(1 for k in high_signal_keywords if k in diff_text)

    if change_ratio > 0.3 or keyword_hits >= 3:
        return SiteChangeSignificance.HIGH
    if change_ratio > 0.1 or keyword_hits >= 1:
        return SiteChangeSignificance.MEDIUM
    return SiteChangeSignificance.LOW


def _summarize_diff(diff_lines: List[str], max_length: int = 500) -> str:
    """Create a human-readable summary of the diff."""
    added = [
        line[1:].strip() for line in diff_lines
        if line.startswith("+") and not line.startswith("+++") and line[1:].strip()
    ]
    removed = [
        line[1:].strip() for line in diff_lines
        if line.startswith("-") and not line.startswith("---") and line[1:].strip()
    ]

    parts = []
    if added:
        parts.append(f"Added: {'; '.join(added[:5])}")
    if removed:
        parts.append(f"Removed: {'; '.join(removed[:5])}")

    summary = " | ".join(parts)
    return summary[:max_length] if summary else "Minor formatting changes"


# ──────────────────────────────────────────────
# Main Monitor Pipeline
# ──────────────────────────────────────────────

def run_site_monitor(
    monitored_pages: Optional[List[Dict[str, Any]]] = None,
    monitored_sitemaps: Optional[List[str]] = None,
    snapshot_dir: str = "data/site_snapshots",
    data_dir: str = "data",
) -> List[SiteChangeRecord]:
    """Run the full site monitoring pipeline.

    Returns a list of detected changes.
    """
    all_changes: List[SiteChangeRecord] = []

    # ── Sitemap Diffing ──
    if monitored_sitemaps:
        sitemap_changes = _check_sitemaps(monitored_sitemaps, data_dir)
        all_changes.extend(sitemap_changes)

    # ── Page Content Diffing ──
    if monitored_pages:
        page_changes = _check_pages(monitored_pages, snapshot_dir)
        all_changes.extend(page_changes)

    # Save changes
    if all_changes:
        existing = load_json(os.path.join(data_dir, "site_changes.json"), default=[])
        existing_ids = {c.get("id") for c in existing}
        new_records = [
            c.model_dump(mode="json") for c in all_changes
            if c.id not in existing_ids
        ]
        if new_records:
            existing.extend(new_records)
            atomic_write_json(os.path.join(data_dir, "site_changes.json"), existing)

    logger.info(f"Site monitor complete: {len(all_changes)} changes detected")
    return all_changes


def _check_sitemaps(
    sitemap_urls: List[str],
    data_dir: str,
) -> List[SiteChangeRecord]:
    """Check sitemaps for new/removed URLs."""
    changes = []
    sitemap_state_path = os.path.join(data_dir, "sitemap_urls.json")
    previous_state = load_json(sitemap_state_path, default={})

    for sitemap_url in sitemap_urls:
        logger.info(f"Checking sitemap: {sitemap_url}")
        current_urls = fetch_sitemap_urls(sitemap_url)

        if not current_urls:
            logger.warning(f"No URLs from {sitemap_url} — skipping")
            continue

        prev_urls = set(previous_state.get(sitemap_url, []))

        if not prev_urls:
            # First run — just store the baseline
            logger.info(f"First sitemap snapshot: {len(current_urls)} URLs")
            previous_state[sitemap_url] = list(current_urls)
            continue

        new_urls, removed_urls = diff_sitemaps(current_urls, prev_urls)

        # Create change records for new URLs
        for url in new_urls:
            category = _classify_url(url)
            significance = _url_significance(url)

            # Skip low-significance noise (translation pages, media assets, etc.)
            if significance == SiteChangeSignificance.LOW:
                if any(skip in url.lower() for skip in ["/media/", "/image", ".jpg", ".png", ".pdf", "/lang/"]):
                    continue

            change = SiteChangeRecord(
                id=_generate_change_id(url, "new_page"),
                detected_date=date.today(),
                site_domain=_extract_domain(url),
                url=url,
                change_type=SiteChangeType.NEW_SITEMAP_URL,
                significance=significance,
                category=category,
                summary=f"New URL detected in sitemap: {url}",
            )
            changes.append(change)
            logger.info(f"  NEW URL [{significance.value}]: {url}")

        # Create change records for removed URLs (less common but notable)
        for url in list(removed_urls)[:10]:  # Cap to avoid noise
            category = _classify_url(url)
            if category:  # Only track removals of categorizable pages
                change = SiteChangeRecord(
                    id=_generate_change_id(url, "removed"),
                    detected_date=date.today(),
                    site_domain=_extract_domain(url),
                    url=url,
                    change_type=SiteChangeType.REMOVED_PAGE,
                    significance=SiteChangeSignificance.MEDIUM,
                    category=category,
                    summary=f"URL removed from sitemap: {url}",
                )
                changes.append(change)

        # Update state
        previous_state[sitemap_url] = list(current_urls)

    atomic_write_json(sitemap_state_path, previous_state)
    return changes


def _check_pages(
    monitored_pages: List[Dict[str, Any]],
    snapshot_dir: str,
) -> List[SiteChangeRecord]:
    """Check monitored pages for content changes."""
    changes = []
    page_state_path = os.path.join(snapshot_dir, "_page_hashes.json")
    page_hashes = load_json(page_state_path, default={})

    for page_cfg in monitored_pages:
        url = page_cfg.get("url", "")
        label = page_cfg.get("label", url)
        category_str = page_cfg.get("category")

        if not url:
            continue

        logger.info(f"Checking page: {label} ({url})")

        # Fetch and snapshot
        text, content_hash, links, headings = snapshot_page(url, snapshot_dir, label)
        if not text:
            logger.warning(f"  Failed to fetch {url}")
            continue

        prev_hash = page_hashes.get(url, {}).get("hash")
        prev_snapshot_path = page_hashes.get(url, {}).get("snapshot_path")

        if prev_hash is None:
            # First snapshot — store baseline
            safe_name = re.sub(r"[^a-zA-Z0-9]", "_", url)[:80]
            snapshot_path = os.path.join(snapshot_dir, f"{safe_name}.txt")
            page_hashes[url] = {
                "hash": content_hash,
                "snapshot_path": snapshot_path,
                "last_checked": str(date.today()),
            }
            logger.info(f"  First snapshot stored (hash: {content_hash[:8]})")
            continue

        if content_hash == prev_hash:
            page_hashes[url]["last_checked"] = str(date.today())
            logger.debug(f"  No changes detected")
            continue

        # Content changed — compute diff
        previous_text = ""
        if prev_snapshot_path and os.path.exists(prev_snapshot_path):
            with open(prev_snapshot_path) as f:
                previous_text = f.read()

        diff_lines, change_ratio = diff_page_content(text, previous_text)
        significance = _diff_significance(change_ratio, diff_lines)
        diff_snippet = _summarize_diff(diff_lines)

        # Parse category
        category = None
        if category_str:
            try:
                category = AnnouncementCategory(category_str)
            except ValueError:
                pass

        change = SiteChangeRecord(
            id=_generate_change_id(url, "content_change"),
            detected_date=date.today(),
            site_domain=_extract_domain(url),
            url=url,
            change_type=SiteChangeType.CONTENT_CHANGE,
            significance=significance,
            category=category,
            summary=f"{label}: content changed ({change_ratio:.0%} modified)",
            diff_snippet=diff_snippet,
            previous_snapshot_hash=prev_hash,
            current_snapshot_hash=content_hash,
        )
        changes.append(change)
        logger.info(
            f"  CHANGED [{significance.value}] {label}: "
            f"{change_ratio:.0%} modified — {diff_snippet[:80]}"
        )

        # Update stored state
        safe_name = re.sub(r"[^a-zA-Z0-9]", "_", url)[:80]
        snapshot_path = os.path.join(snapshot_dir, f"{safe_name}.txt")
        page_hashes[url] = {
            "hash": content_hash,
            "snapshot_path": snapshot_path,
            "last_checked": str(date.today()),
        }

        rate_limit_sleep(1.0, 2.5)

    atomic_write_json(page_state_path, page_hashes)
    return changes


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return parsed.netloc or "unknown"


# ──────────────────────────────────────────────
# Corroboration Matching (Claude-powered)
# ──────────────────────────────────────────────

def match_changes_to_clusters(
    changes: List[SiteChangeRecord],
    open_clusters: List[Dict[str, Any]],
    model: str = "claude-sonnet-4-6",
) -> List[Dict[str, Any]]:
    """Use Claude to match site changes to existing rumor clusters.

    Returns updated clusters with corroboration flags.
    """
    if not changes or not open_clusters:
        return open_clusters

    # Only match medium/high significance changes
    significant = [c for c in changes if c.significance != SiteChangeSignificance.LOW]
    if not significant:
        return open_clusters

    from engines.llm_client import chat_completion
    from engines.json_parser import parse_llm_json

    # Format changes
    changes_text = "\n".join(
        f"[{c.id}] {c.change_type.value} | {c.category.value if c.category else 'unknown'} | "
        f"{c.significance.value} | {c.url}\n  {c.summary}\n  Diff: {c.diff_snippet[:200]}"
        for c in significant
    )

    # Format clusters
    clusters_text = "\n".join(
        f"[{c.get('cluster_id', '')}] (score: {c.get('score', 'N/A')}) {c.get('cluster_summary', '')}"
        for c in open_clusters
        if c.get("resolution", {}).get("status", "unresolved") == "unresolved"
    )

    prompt = (
        "You are matching detected changes on official LDS Church websites to existing "
        "rumor clusters to determine if a website change corroborates a rumor.\n\n"
        "A corroboration means the website change is consistent with the rumor being true. "
        "For example:\n"
        "- A new /temples/boise-idaho URL appearing corroborates a rumor about a Boise temple\n"
        "- Handbook text changes about missionary age corroborate rumors about policy changes\n"
        "- A new leadership page corroborates rumors about a calling\n\n"
        "For each website change, determine:\n"
        "1. Does it corroborate any existing rumor cluster?\n"
        "2. If yes, which cluster_id(s)?\n"
        "3. How strong is the corroboration? (strong / moderate / weak)\n\n"
        "Respond with a JSON array:\n"
        '{"change_id": "...", "corroborates": [{"cluster_id": "...", "strength": "strong|moderate|weak"}], '
        '"standalone_signal": true/false, "standalone_summary": "..." }\n\n'
        "If a change doesn't match any cluster but is still significant, set standalone_signal: true "
        "and provide a standalone_summary describing what it might indicate.\n\n"
        f"Website changes detected:\n{changes_text}\n\n"
        f"Open rumor clusters:\n{clusters_text}"
    )

    response = chat_completion(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        temperature=0.2,
        max_tokens=4096,
    )
    matches = parse_llm_json(response, expected_type=list, context="site_change_match")

    # Apply corroborations
    cluster_lookup = {c.get("cluster_id", ""): c for c in open_clusters}
    change_lookup = {c.id: c for c in significant}

    for match in matches:
        change_id = match.get("change_id", "")
        change = change_lookup.get(change_id)

        for corr in match.get("corroborates", []):
            cluster_id = corr.get("cluster_id", "")
            if cluster_id in cluster_lookup:
                cluster = cluster_lookup[cluster_id]

                # Add site change corroboration to cluster
                site_ids = cluster.setdefault("corroborating_site_change_ids", [])
                if change_id not in site_ids:
                    site_ids.append(change_id)
                cluster["has_site_corroboration"] = True

                if change:
                    change.corroborates_cluster_ids.append(cluster_id)

                logger.info(
                    f"  Site change {change_id} corroborates cluster {cluster_id} "
                    f"({corr.get('strength', 'unknown')})"
                )

    return open_clusters


def generate_standalone_signals(
    changes: List[SiteChangeRecord],
    model: str = "claude-sonnet-4-6",
) -> List[Dict[str, Any]]:
    """Generate rumor-like records from significant site changes that don't
    match any existing cluster.

    These become standalone entries in the digest.
    """
    # Only unmatched high/medium changes
    unmatched = [
        c for c in changes
        if not c.corroborates_cluster_ids
        and c.significance in (SiteChangeSignificance.HIGH, SiteChangeSignificance.MEDIUM)
    ]

    if not unmatched:
        return []

    standalone = []
    for change in unmatched:
        standalone.append({
            "cluster_id": change.id,
            "cluster_summary": f"[SITE SIGNAL] {change.summary}",
            "rumor_ids": [],
            "independent_source_count": 1,
            "earliest_post_date": str(change.detected_date),
            "source_type": "church_site",
            "url": change.url,
            "change_type": change.change_type.value,
            "significance": change.significance.value,
            "category": change.category.value if change.category else "other",
            "diff_snippet": change.diff_snippet,
            "resolution": {"status": "unresolved"},
            # Standalone signals get a fixed moderate score since they're
            # from an official source but lack rumor context
            "score": 0.45 if change.significance == SiteChangeSignificance.HIGH else 0.30,
            "confidence_tier": "medium" if change.significance == SiteChangeSignificance.HIGH else "low",
            "score_explanation": f"Church website signal: {change.change_type.value} on {_extract_domain(change.url)}",
        })

    logger.info(f"Generated {len(standalone)} standalone site signals")
    return standalone


# ──────────────────────────────────────────────
# Entry Point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Monitor Church websites for changes")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--snapshot-dir", default="data/site_snapshots")
    parser.add_argument("--sitemaps-only", action="store_true")
    parser.add_argument("--pages-only", action="store_true")
    args = parser.parse_args()

    from engines.logging_config import setup_logging
    setup_logging("INFO")

    from models import SiteMonitorConfig
    config = SiteMonitorConfig()

    sitemaps = None if args.pages_only else config.monitored_sitemaps
    pages = None if args.sitemaps_only else config.monitored_pages

    changes = run_site_monitor(
        monitored_pages=pages,
        monitored_sitemaps=sitemaps,
        snapshot_dir=args.snapshot_dir,
        data_dir=args.data_dir,
    )

    for c in changes:
        print(f"  [{c.significance.value}] {c.change_type.value}: {c.summary[:80]}")
