"""
Tests for the classifier module — validates output structure and enum handling.
Does NOT call Claude API (tests parsing and data mapping only).
"""
import os
import sys
import pytest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import (
    RumorRecord, RumorFeatures, AnnouncementCategory, Specificity,
    ClaimedSourceType, LanguageConfidence, Falsifiability, SourcePlatform,
)
from rumor_engine.classifier import _safe_enum, _generate_rumor_id, _format_batch


class TestSafeEnum:
    def test_valid_enum_value(self):
        result = _safe_enum(AnnouncementCategory, "temple_announcement", AnnouncementCategory.OTHER)
        assert result == AnnouncementCategory.TEMPLE_ANNOUNCEMENT

    def test_invalid_enum_value(self):
        result = _safe_enum(AnnouncementCategory, "nonexistent", AnnouncementCategory.OTHER)
        assert result == AnnouncementCategory.OTHER

    def test_none_value(self):
        result = _safe_enum(AnnouncementCategory, None, AnnouncementCategory.OTHER)
        assert result == AnnouncementCategory.OTHER

    def test_case_insensitive(self):
        result = _safe_enum(Specificity, "CITY_LEVEL", Specificity.VAGUE)
        assert result == Specificity.CITY_LEVEL

    def test_whitespace_handling(self):
        result = _safe_enum(ClaimedSourceType, "  insider_family  ", ClaimedSourceType.SPECULATION)
        assert result == ClaimedSourceType.INSIDER_FAMILY


class TestRumorIdGeneration:
    def test_deterministic(self):
        id1 = _generate_rumor_id("abc123", 0)
        id2 = _generate_rumor_id("abc123", 0)
        assert id1 == id2

    def test_different_inputs(self):
        id1 = _generate_rumor_id("abc123", 0)
        id2 = _generate_rumor_id("def456", 0)
        assert id1 != id2

    def test_prefix_format(self):
        rid = _generate_rumor_id("test", 0)
        assert rid.startswith("rum-")
        assert str(date.today().year) in rid


class TestFormatBatch:
    def test_format_single_post(self):
        posts = [{
            "id": "abc123",
            "subreddit": "latterdaysaints",
            "author": "testuser",
            "created_utc": 1700000000,
            "title": "Heard about new temple",
            "body": "My bishop mentioned something about a new temple in Idaho",
        }]
        result = _format_batch(posts)
        assert "abc123" in result
        assert "r/latterdaysaints" in result
        assert "testuser" in result
        assert "Idaho" in result

    def test_truncates_long_body(self):
        posts = [{
            "id": "long",
            "subreddit": "lds",
            "author": "user",
            "created_utc": 0,
            "title": "",
            "body": "x" * 2000,
        }]
        result = _format_batch(posts)
        # Body should be truncated to 1000 chars
        assert len(result) < 2000


class TestRumorRecordCreation:
    def test_valid_rumor_record(self):
        record = RumorRecord(
            id="rum-2025-abc12",
            source_platform=SourcePlatform.REDDIT,
            source_sub="r/latterdaysaints",
            source_url="https://reddit.com/r/latterdaysaints/comments/abc",
            author="u/testuser",
            post_date=date(2025, 6, 15),
            raw_text="My uncle said there's a new temple coming to Boise",
            extracted_claim="A new temple will be announced in Boise, Idaho",
            features=RumorFeatures(
                category=AnnouncementCategory.TEMPLE_ANNOUNCEMENT,
                specificity=Specificity.CITY_LEVEL,
                claimed_source_type=ClaimedSourceType.INSIDER_FAMILY,
                language_confidence=LanguageConfidence.MODERATE,
                falsifiability=Falsifiability.HIGH,
            ),
        )
        assert record.id.startswith("rum-")
        assert record.features.category == AnnouncementCategory.TEMPLE_ANNOUNCEMENT

    def test_invalid_id_prefix(self):
        with pytest.raises(ValueError, match="must start with 'rum-'"):
            RumorRecord(
                id="bad-prefix",
                source_platform=SourcePlatform.REDDIT,
                source_url="https://reddit.com/test",
                author="u/test",
                post_date=date.today(),
                raw_text="test",
                extracted_claim="test",
                features=RumorFeatures(
                    category=AnnouncementCategory.OTHER,
                    specificity=Specificity.VAGUE,
                    claimed_source_type=ClaimedSourceType.SPECULATION,
                    language_confidence=LanguageConfidence.LOW,
                    falsifiability=Falsifiability.LOW,
                ),
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
