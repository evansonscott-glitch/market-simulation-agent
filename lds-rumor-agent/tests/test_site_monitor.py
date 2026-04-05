"""
Tests for Church website change detection system.
"""
import os
import sys
import tempfile
import pytest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import (
    SiteChangeRecord, SiteChangeType, SiteChangeSignificance,
    AnnouncementCategory, SiteMonitorConfig,
)
from scrapers.church_site_monitor import (
    _extract_text, _content_hash, _classify_url, _url_significance,
    _generate_change_id, _summarize_diff,
    diff_sitemaps, diff_page_content, generate_standalone_signals,
)


# ──────────────────────────────────────────────
# Text Extraction Tests
# ──────────────────────────────────────────────

class TestTextExtraction:
    def test_extracts_visible_text(self):
        html = "<html><body><h1>Title</h1><p>Hello world</p></body></html>"
        text, links, headings = _extract_text(html)
        assert "Title" in text
        assert "Hello world" in text
        assert "Title" in headings

    def test_strips_scripts_and_styles(self):
        html = (
            "<html><body>"
            "<script>var x = 1;</script>"
            "<style>.foo { color: red; }</style>"
            "<p>Visible text</p>"
            "</body></html>"
        )
        text, _, _ = _extract_text(html)
        assert "var x" not in text
        assert "color" not in text
        assert "Visible text" in text

    def test_extracts_links(self):
        html = '<a href="/temples/boise">Boise Temple</a>'
        _, links, _ = _extract_text(html)
        assert "/temples/boise" in links

    def test_extracts_headings(self):
        html = "<h1>Main</h1><h2>Sub</h2><h3>Detail</h3><p>body</p>"
        _, _, headings = _extract_text(html)
        assert "Main" in headings
        assert "Sub" in headings
        assert "Detail" in headings


# ──────────────────────────────────────────────
# Content Hash Tests
# ──────────────────────────────────────────────

class TestContentHash:
    def test_deterministic(self):
        h1 = _content_hash("hello world")
        h2 = _content_hash("hello world")
        assert h1 == h2

    def test_normalizes_whitespace(self):
        h1 = _content_hash("hello  world")
        h2 = _content_hash("hello world")
        assert h1 == h2

    def test_case_insensitive(self):
        h1 = _content_hash("Hello World")
        h2 = _content_hash("hello world")
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = _content_hash("hello")
        h2 = _content_hash("goodbye")
        assert h1 != h2


# ──────────────────────────────────────────────
# URL Classification Tests
# ──────────────────────────────────────────────

class TestUrlClassification:
    def test_temple_url(self):
        assert _classify_url("https://churchofjesuschrist.org/temples/boise-idaho") == AnnouncementCategory.TEMPLE_ANNOUNCEMENT

    def test_handbook_url(self):
        assert _classify_url("https://churchofjesuschrist.org/study/manual/general-handbook/38") == AnnouncementCategory.POLICY_UPDATE

    def test_leadership_url(self):
        assert _classify_url("https://churchofjesuschrist.org/callings/leader-resources") == AnnouncementCategory.LEADERSHIP_CHANGE

    def test_program_url(self):
        assert _classify_url("https://churchofjesuschrist.org/youth/seminary") == AnnouncementCategory.PROGRAM

    def test_store_url(self):
        assert _classify_url("https://store.churchofjesuschrist.org/new-item") == AnnouncementCategory.PROGRAM

    def test_unknown_url(self):
        assert _classify_url("https://churchofjesuschrist.org/about") is None


class TestUrlSignificance:
    def test_temple_is_high(self):
        assert _url_significance("https://example.com/temples/new") == SiteChangeSignificance.HIGH

    def test_handbook_is_high(self):
        assert _url_significance("https://example.com/handbook/chapter-5") == SiteChangeSignificance.HIGH

    def test_callings_is_medium(self):
        assert _url_significance("https://example.com/callings/bishop") == SiteChangeSignificance.MEDIUM

    def test_generic_is_low(self):
        assert _url_significance("https://example.com/about") == SiteChangeSignificance.LOW


# ──────────────────────────────────────────────
# Sitemap Diffing Tests
# ──────────────────────────────────────────────

class TestSitemapDiff:
    def test_detects_new_urls(self):
        old = {"https://a.com/1", "https://a.com/2"}
        new = {"https://a.com/1", "https://a.com/2", "https://a.com/3"}
        added, removed = diff_sitemaps(new, old)
        assert added == {"https://a.com/3"}
        assert removed == set()

    def test_detects_removed_urls(self):
        old = {"https://a.com/1", "https://a.com/2"}
        new = {"https://a.com/1"}
        added, removed = diff_sitemaps(new, old)
        assert added == set()
        assert removed == {"https://a.com/2"}

    def test_no_changes(self):
        urls = {"https://a.com/1", "https://a.com/2"}
        added, removed = diff_sitemaps(urls, urls)
        assert added == set()
        assert removed == set()


# ──────────────────────────────────────────────
# Page Content Diffing Tests
# ──────────────────────────────────────────────

class TestPageDiff:
    def test_detects_content_change(self):
        old = "Line 1\nLine 2\nLine 3"
        new = "Line 1\nLine 2 modified\nLine 3"
        diff_lines, ratio = diff_page_content(new, old)
        assert len(diff_lines) > 0
        assert ratio > 0

    def test_no_change(self):
        text = "Same content\nNo changes"
        diff_lines, ratio = diff_page_content(text, text)
        assert len(diff_lines) == 0
        assert ratio == 0

    def test_entirely_new_content(self):
        diff_lines, ratio = diff_page_content("New content", "")
        assert ratio == 1.0

    def test_summarize_diff(self):
        diff = [
            "--- previous",
            "+++ current",
            "-Old line",
            "+New line about Boise temple",
        ]
        summary = _summarize_diff(diff)
        assert "Boise temple" in summary
        assert "Added" in summary


# ──────────────────────────────────────────────
# Change ID Generation Tests
# ──────────────────────────────────────────────

class TestChangeId:
    def test_format(self):
        cid = _generate_change_id("https://example.com/page", "content_change")
        assert cid.startswith("site-")
        assert str(date.today().year) in cid

    def test_deterministic(self):
        id1 = _generate_change_id("https://a.com", "new_page")
        id2 = _generate_change_id("https://a.com", "new_page")
        assert id1 == id2


# ──────────────────────────────────────────────
# Standalone Signal Generation Tests
# ──────────────────────────────────────────────

class TestStandaloneSignals:
    def test_generates_from_unmatched_changes(self):
        changes = [
            SiteChangeRecord(
                id="site-2026-abc123",
                detected_date=date.today(),
                site_domain="churchofjesuschrist.org",
                url="https://churchofjesuschrist.org/temples/new-page",
                change_type=SiteChangeType.NEW_SITEMAP_URL,
                significance=SiteChangeSignificance.HIGH,
                category=AnnouncementCategory.TEMPLE_ANNOUNCEMENT,
                summary="New temple page detected",
            ),
        ]
        signals = generate_standalone_signals(changes)
        assert len(signals) == 1
        assert signals[0]["source_type"] == "church_site"
        assert "[SITE SIGNAL]" in signals[0]["cluster_summary"]
        assert signals[0]["score"] == 0.45  # High significance default

    def test_skips_low_significance(self):
        changes = [
            SiteChangeRecord(
                id="site-2026-low123",
                detected_date=date.today(),
                site_domain="churchofjesuschrist.org",
                url="https://churchofjesuschrist.org/about",
                change_type=SiteChangeType.CONTENT_CHANGE,
                significance=SiteChangeSignificance.LOW,
                summary="Minor change",
            ),
        ]
        signals = generate_standalone_signals(changes)
        assert len(signals) == 0

    def test_skips_already_matched(self):
        changes = [
            SiteChangeRecord(
                id="site-2026-matched",
                detected_date=date.today(),
                site_domain="churchofjesuschrist.org",
                url="https://churchofjesuschrist.org/temples/boise",
                change_type=SiteChangeType.NEW_SITEMAP_URL,
                significance=SiteChangeSignificance.HIGH,
                summary="New temple page",
                corroborates_cluster_ids=["cluster-0001"],  # Already matched
            ),
        ]
        signals = generate_standalone_signals(changes)
        assert len(signals) == 0


# ──────────────────────────────────────────────
# Model Tests
# ──────────────────────────────────────────────

class TestSiteChangeRecord:
    def test_valid_record(self):
        record = SiteChangeRecord(
            id="site-2026-abc123",
            detected_date=date.today(),
            site_domain="churchofjesuschrist.org",
            url="https://churchofjesuschrist.org/temples/new",
            change_type=SiteChangeType.NEW_PAGE,
            significance=SiteChangeSignificance.HIGH,
            category=AnnouncementCategory.TEMPLE_ANNOUNCEMENT,
            summary="New temple page added",
        )
        assert record.id.startswith("site-")

    def test_invalid_id(self):
        with pytest.raises(ValueError, match="must start with 'site-'"):
            SiteChangeRecord(
                id="bad-id",
                site_domain="test.com",
                url="https://test.com",
                change_type=SiteChangeType.NEW_PAGE,
            )


class TestSiteMonitorConfig:
    def test_defaults(self):
        config = SiteMonitorConfig()
        assert config.enabled is True
        assert len(config.monitored_sitemaps) >= 1
        assert len(config.monitored_pages) >= 5
        assert any("temple" in p["url"].lower() for p in config.monitored_pages)
        assert any("handbook" in p["url"].lower() for p in config.monitored_pages)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
