"""
End-to-end pipeline tests with mock data.
Tests the data flow without making actual API calls.
"""
import os
import sys
import json
import pytest
import tempfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import (
    AnnouncementRecord, AnnouncementCategory, Location,
    PriorTables, FeatureStats, ConfidenceTier,
    DigestRecord,
)
from scrapers.utils import atomic_write_json, load_json
from scrapers.reddit_scraper import filter_candidates
from scrapers.newsroom_scraper import (
    deduplicate_announcements, _classify_category, _parse_date,
)
from rumor_engine.scorer import (
    build_prior_tables, score_rumor, calibration_check, score_clusters,
)
from rumor_engine.resolver import check_stale_rumors
from agent.digest_generator import build_digest_record


# ──────────────────────────────────────────────
# Reddit Filtering Tests
# ──────────────────────────────────────────────

class TestRedditFiltering:
    def test_keyword_filter(self):
        posts = [
            {"id": "1", "title": "I heard about a new temple", "body": "", "num_comments": 0},
            {"id": "2", "title": "General discussion", "body": "Just chatting", "num_comments": 0},
            {"id": "3", "title": "Speculation about conference", "body": "", "num_comments": 0},
        ]
        candidates = filter_candidates(posts)
        assert len(candidates) == 2  # Posts 1 and 3 match keywords

    def test_engagement_filter(self):
        posts = [
            {"id": "1", "title": "What about the temple?", "body": "church plans", "num_comments": 15},
            {"id": "2", "title": "Random stuff", "body": "nothing here at all", "num_comments": 50},
        ]
        candidates = filter_candidates(posts, keywords=["temple"], min_engagement=10)
        assert len(candidates) == 1  # Only post 1 has temple keyword

    def test_deduplication(self):
        posts = [
            {"id": "1", "title": "Rumor about temple", "body": "", "num_comments": 0},
            {"id": "1", "title": "Rumor about temple", "body": "", "num_comments": 0},  # Duplicate
        ]
        candidates = filter_candidates(posts)
        assert len(candidates) == 1


# ──────────────────────────────────────────────
# Newsroom Utility Tests
# ──────────────────────────────────────────────

class TestNewsroomUtils:
    def test_category_classification(self):
        assert _classify_category("New Temple Announced", "") == AnnouncementCategory.TEMPLE_ANNOUNCEMENT
        assert _classify_category("Elder Smith Called as Apostle", "") == AnnouncementCategory.LEADERSHIP_CHANGE
        assert _classify_category("Handbook Update Released", "") == AnnouncementCategory.POLICY_UPDATE
        assert _classify_category("Random News", "") == AnnouncementCategory.OTHER

    def test_date_parsing(self):
        assert _parse_date("2025-10-05") == date(2025, 10, 5)
        assert _parse_date("October 5, 2025") == date(2025, 10, 5)
        assert _parse_date("2025-10-05T14:30:00Z") == date(2025, 10, 5)
        assert _parse_date(None) is None
        assert _parse_date("") is None
        assert _parse_date("not a date") is None

    def test_deduplication(self):
        records = [
            AnnouncementRecord(
                id="ann-001", date=date(2025, 10, 5),
                category=AnnouncementCategory.TEMPLE_ANNOUNCEMENT,
                title="Temple in Tonga", summary="Short", source_url="http://a",
            ),
            AnnouncementRecord(
                id="ann-002", date=date(2025, 10, 5),
                category=AnnouncementCategory.TEMPLE_ANNOUNCEMENT,
                title="Temple in Tonga", summary="Longer summary with more info",
                source_url="http://b",
            ),
        ]
        deduped = deduplicate_announcements(records)
        assert len(deduped) == 1
        assert "Longer" in deduped[0].summary  # Kept the one with more info


# ──────────────────────────────────────────────
# Stale Rumor Resolution Tests
# ──────────────────────────────────────────────

class TestStaleRumors:
    def test_marks_old_rumors_as_denied(self):
        clusters = [
            {
                "cluster_id": "c1",
                "earliest_post_date": "2025-01-01",  # Very old
                "resolution": {"status": "unresolved"},
            },
            {
                "cluster_id": "c2",
                "earliest_post_date": str(date.today()),  # Fresh
                "resolution": {"status": "unresolved"},
            },
        ]
        updated = check_stale_rumors(clusters, stale_days=180)

        c1 = next(c for c in updated if c["cluster_id"] == "c1")
        c2 = next(c for c in updated if c["cluster_id"] == "c2")
        assert c1["resolution"]["status"] == "denied"
        assert c2["resolution"]["status"] == "unresolved"


# ──────────────────────────────────────────────
# Digest Record Tests
# ──────────────────────────────────────────────

class TestDigestRecord:
    def test_build_digest(self):
        scored = [
            {
                "cluster_id": "c1",
                "cluster_summary": "Temple in Boise",
                "score": 0.72,
                "confidence_tier": "high",
                "score_explanation": "Strong signals",
                "rumor_ids": ["r1", "r2"],
            },
        ]
        resolved = []
        stats = {"total_tracked": 10, "resolved_this_week": 0}

        record = build_digest_record(
            scored, resolved, stats,
            week_start=date(2026, 3, 30),
            week_end=date(2026, 4, 5),
        )
        assert record.digest_id.startswith("digest-")
        assert len(record.new_rumors) == 1
        assert record.new_rumors[0].score == 0.72


# ──────────────────────────────────────────────
# File I/O Tests
# ──────────────────────────────────────────────

class TestFileIO:
    def test_atomic_write_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.json")
            data = {"key": "value", "list": [1, 2, 3]}
            atomic_write_json(path, data)
            loaded = load_json(path)
            assert loaded == data

    def test_load_missing_file(self):
        result = load_json("/nonexistent/file.json", default=[])
        assert result == []

    def test_load_corrupt_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json{{{")
            path = f.name
        try:
            result = load_json(path, default={"fallback": True})
            assert result == {"fallback": True}
        finally:
            os.unlink(path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
