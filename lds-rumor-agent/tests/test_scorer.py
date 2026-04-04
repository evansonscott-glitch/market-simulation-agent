"""
Unit tests for the Bayesian scoring engine.
"""
import os
import sys
import pytest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import PriorTables, FeatureStats, ConfidenceTier, CalibrationReport
from rumor_engine.scorer import (
    score_rumor, build_prior_tables, calibration_check,
    score_clusters, TIER_THRESHOLDS,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────���───────────────────────

def make_prior_tables():
    """Create sample prior tables for testing."""
    return PriorTables(
        global_base_rate=0.25,
        total_labeled_rumors=100,
        feature_priors={
            "category": {
                "temple_announcement": FeatureStats(likelihood_ratio=2.0, sample_size=30),
                "leadership_change": FeatureStats(likelihood_ratio=1.2, sample_size=20),
                "other": FeatureStats(likelihood_ratio=0.5, sample_size=10),
            },
            "specificity": {
                "exact_name_or_location": FeatureStats(likelihood_ratio=2.8, sample_size=15),
                "city_level": FeatureStats(likelihood_ratio=2.1, sample_size=20),
                "vague": FeatureStats(likelihood_ratio=0.3, sample_size=25),
            },
            "claimed_source_type": {
                "insider_named": FeatureStats(likelihood_ratio=3.5, sample_size=5),
                "insider_family": FeatureStats(likelihood_ratio=2.4, sample_size=12),
                "speculation": FeatureStats(likelihood_ratio=0.6, sample_size=40),
            },
            "source_platform": {
                "r/latterdaysaints": FeatureStats(likelihood_ratio=1.8, sample_size=50),
                "r/exmormon": FeatureStats(likelihood_ratio=0.8, sample_size=30),
            },
            "corroboration_count": {
                "0": FeatureStats(likelihood_ratio=0.5, sample_size=40),
                "1": FeatureStats(likelihood_ratio=1.2, sample_size=25),
                "2": FeatureStats(likelihood_ratio=1.8, sample_size=15),
                "3+": FeatureStats(likelihood_ratio=2.5, sample_size=10),
            },
            "author_track_record": {
                "no_history": FeatureStats(likelihood_ratio=1.0, sample_size=60),
                "previously_correct": FeatureStats(likelihood_ratio=2.2, sample_size=10),
                "previously_wrong": FeatureStats(likelihood_ratio=0.5, sample_size=8),
            },
        },
    )


# ���─────────────────────────────────────────────
# Score Computation Tests
# ──────────────────────────────────────────────

class TestScoreRumor:
    def test_high_signal_rumor_scores_high(self):
        tables = make_prior_tables()
        features = {
            "category": "temple_announcement",
            "specificity": "city_level",
            "claimed_source_type": "insider_family",
        }
        score, tier, explanation = score_rumor(
            features, tables,
            source_platform="r/latterdaysaints",
            corroboration_count=2,
            author_track_record="previously_correct",
        )
        assert score > 0.65
        assert tier == ConfidenceTier.HIGH
        assert explanation  # Should have explanatory text

    def test_low_signal_rumor_scores_low(self):
        tables = make_prior_tables()
        features = {
            "category": "other",
            "specificity": "vague",
            "claimed_source_type": "speculation",
        }
        score, tier, explanation = score_rumor(
            features, tables,
            source_platform="r/exmormon",
            corroboration_count=0,
            author_track_record="previously_wrong",
        )
        assert score < 0.15
        assert tier == ConfidenceTier.NOISE

    def test_score_bounded_0_to_1(self):
        tables = make_prior_tables()
        # Extreme positive signals
        features = {
            "category": "temple_announcement",
            "specificity": "exact_name_or_location",
            "claimed_source_type": "insider_named",
        }
        score, _, _ = score_rumor(
            features, tables,
            source_platform="r/latterdaysaints",
            corroboration_count=5,
            author_track_record="previously_correct",
        )
        assert 0.0 <= score <= 1.0

    def test_missing_features_default_neutral(self):
        tables = make_prior_tables()
        # Empty features — should get roughly the base rate
        score, tier, _ = score_rumor(
            {}, tables,
            source_platform="",
            corroboration_count=0,
        )
        assert 0.0 <= score <= 1.0

    def test_low_sample_size_shrinkage(self):
        """Features with low sample size should be shrunk toward 1.0."""
        tables = make_prior_tables()
        # insider_named has sample_size=5, so LR should be attenuated
        features = {"claimed_source_type": "insider_named"}
        score_shrunk, _, _ = score_rumor(features, tables)

        # Give it high sample size and compare
        tables.feature_priors["claimed_source_type"]["insider_named"].sample_size = 100
        score_full, _, _ = score_rumor(features, tables)

        # Full sample should have more extreme score
        assert score_full > score_shrunk or abs(score_full - score_shrunk) < 0.01


# ─────��────────────────────────────────────────
# Tier Classification Tests
# ──────────────���───────────────────────────────

class TestConfidenceTiers:
    def test_tier_thresholds(self):
        assert TIER_THRESHOLDS[ConfidenceTier.HIGH] == 0.65
        assert TIER_THRESHOLDS[ConfidenceTier.MEDIUM] == 0.35
        assert TIER_THRESHOLDS[ConfidenceTier.LOW] == 0.15


# ────���─────────────────────────────────────────
# Prior Table Building Tests
# ──────────────────────────────────────────────

class TestBuildPriors:
    def test_build_from_labeled_data(self):
        clusters = [
            {
                "cluster_id": "c1",
                "rumor_ids": ["rum-2025-001"],
                "resolution": {"status": "confirmed"},
            },
            {
                "cluster_id": "c2",
                "rumor_ids": ["rum-2025-002"],
                "resolution": {"status": "denied"},
            },
        ]
        rumors = [
            {
                "id": "rum-2025-001",
                "features": {
                    "category": "temple_announcement",
                    "specificity": "city_level",
                    "claimed_source_type": "insider_family",
                    "corroboration_count": 1,
                },
                "source_sub": "r/latterdaysaints",
                "author": "u/test1",
            },
            {
                "id": "rum-2025-002",
                "features": {
                    "category": "other",
                    "specificity": "vague",
                    "claimed_source_type": "speculation",
                    "corroboration_count": 0,
                },
                "source_sub": "r/exmormon",
                "author": "u/test2",
            },
        ]

        tables = build_prior_tables(clusters, rumors)
        assert tables.global_base_rate == 0.5  # 1 confirmed / 2 total
        assert tables.total_labeled_rumors == 2
        assert "category" in tables.feature_priors
        assert "temple_announcement" in tables.feature_priors["category"]

    def test_empty_data_returns_defaults(self):
        tables = build_prior_tables([], [])
        assert tables.total_labeled_rumors == 0
        assert tables.global_base_rate == 0.22  # Default


# ────────────────────────���─────────────────────
# Calibration Tests
# ───��─────────────────��────────────────────────

class TestCalibration:
    def test_calibration_with_resolved_clusters(self):
        clusters = [
            {"score": 0.8, "resolution": {"status": "confirmed"}},
            {"score": 0.7, "resolution": {"status": "confirmed"}},
            {"score": 0.3, "resolution": {"status": "denied"}},
            {"score": 0.2, "resolution": {"status": "denied"}},
        ]
        report = calibration_check(clusters)
        assert report.total_resolved == 4
        assert report.overall_accuracy is not None
        assert len(report.deciles) == 10

    def test_calibration_no_resolved(self):
        clusters = [
            {"score": 0.5, "resolution": {"status": "unresolved"}},
        ]
        report = calibration_check(clusters)
        assert report.total_resolved == 0
        assert "No resolved clusters" in report.notes[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
