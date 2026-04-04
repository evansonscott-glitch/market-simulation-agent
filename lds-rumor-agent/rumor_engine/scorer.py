#!/usr/bin/env python3
"""
Component 4: Bayesian Scoring Engine

Computes posterior probability of a rumor being true using naive Bayes
with likelihood ratios across multiple feature dimensions.

Core formula:
  posterior_odds = prior_odds × LR(category) × LR(specificity) × LR(source_type)
                   × LR(platform) × LR(corroboration) × LR(author_history)

where LR(feature) = P(feature | true) / P(feature | false)

Pure Python — no ML libraries needed.
"""
import os
import sys
import math
from datetime import date
from typing import Dict, List, Optional, Any, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from engines.logging_config import get_logger

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from models import (
    PriorTables, FeatureStats, ConfidenceTier,
    CalibrationReport, DecileBucket,
)
from scrapers.utils import atomic_write_json, load_json

logger = get_logger("rumor_engine.scorer")

# Laplace smoothing constant
LAPLACE_ALPHA = 1.0

# Feature dimensions used for scoring
FEATURE_DIMENSIONS = [
    "category",
    "specificity",
    "claimed_source_type",
    "source_platform",
    "corroboration_count",
    "author_track_record",
]

# Confidence tier thresholds
TIER_THRESHOLDS = {
    ConfidenceTier.HIGH: 0.65,
    ConfidenceTier.MEDIUM: 0.35,
    ConfidenceTier.LOW: 0.15,
}


# ──────────────────────────────────────────────
# Prior Table Construction
# ──────────────────────────────────────────────

def build_prior_tables(
    labeled_clusters: List[Dict[str, Any]],
    rumor_records: List[Dict[str, Any]],
    author_records: Optional[Dict[str, Any]] = None,
) -> PriorTables:
    """Build Bayesian prior tables from labeled training data.

    Args:
        labeled_clusters: Clusters with resolution status (from matcher)
        rumor_records: Individual rumor records with features
        author_records: Optional author track records
    """
    # Count total confirmed vs denied
    total_confirmed = 0
    total_denied = 0
    total_resolved = 0

    for cluster in labeled_clusters:
        res = cluster.get("resolution", {})
        status = res.get("status", "unresolved")
        if status in ("confirmed", "partially_confirmed"):
            total_confirmed += 1
            total_resolved += 1
        elif status == "denied":
            total_denied += 1
            total_resolved += 1

    if total_resolved == 0:
        logger.warning("No resolved clusters — returning default priors")
        return PriorTables(total_labeled_rumors=0)

    global_base_rate = total_confirmed / total_resolved

    # Build a lookup: cluster_id -> resolution
    cluster_res = {}
    cluster_rumor_ids = {}
    for cluster in labeled_clusters:
        cid = cluster.get("cluster_id", "")
        cluster_res[cid] = cluster.get("resolution", {}).get("status", "unresolved")
        cluster_rumor_ids[cid] = set(cluster.get("rumor_ids", []))

    # Map rumor_id -> is_true (via its cluster)
    rumor_truth = {}
    for cid, rids in cluster_rumor_ids.items():
        status = cluster_res.get(cid, "unresolved")
        if status in ("confirmed", "partially_confirmed"):
            for rid in rids:
                rumor_truth[rid] = True
        elif status == "denied":
            for rid in rids:
                rumor_truth[rid] = False

    # Build feature counts
    feature_priors: Dict[str, Dict[str, FeatureStats]] = {}

    # Build rumor lookup
    rumor_lookup = {r.get("id", ""): r for r in rumor_records}

    for dimension in FEATURE_DIMENSIONS:
        feature_priors[dimension] = {}

    for rid, is_true in rumor_truth.items():
        rumor = rumor_lookup.get(rid, {})
        features = rumor.get("features", {})

        # Category
        _count_feature(feature_priors, "category", features.get("category", "other"), is_true)

        # Specificity
        _count_feature(feature_priors, "specificity", features.get("specificity", "vague"), is_true)

        # Claimed source type
        _count_feature(feature_priors, "claimed_source_type", features.get("claimed_source_type", "speculation"), is_true)

        # Source platform
        sub = rumor.get("source_sub", "")
        _count_feature(feature_priors, "source_platform", sub or "unknown", is_true)

        # Corroboration count (bucket into 0, 1, 2, 3+)
        corr = features.get("corroboration_count", 0)
        corr_bucket = str(min(corr, 3)) if corr < 3 else "3+"
        _count_feature(feature_priors, "corroboration_count", corr_bucket, is_true)

        # Author track record
        author = rumor.get("author", "")
        track = "no_history"
        if author_records and author in author_records:
            ar = author_records[author]
            total_pred = ar.get("total_predictions", 0)
            if total_pred > 0:
                ratio = ar.get("correct_predictions", 0) / total_pred
                if ratio >= 0.6:
                    track = "previously_correct"
                elif ratio <= 0.3:
                    track = "previously_wrong"
                else:
                    track = "mixed"
        _count_feature(feature_priors, "author_track_record", track, is_true)

    # Compute likelihood ratios with Laplace smoothing
    for dimension, values in feature_priors.items():
        for value, stats in values.items():
            tp = stats.true_positive_rate or 0  # Using as TP count temporarily
            fp = stats.base_rate or 0  # Using as FP count temporarily
            sample = stats.sample_size

            # Laplace-smoothed rates
            tp_rate = (tp + LAPLACE_ALPHA) / (total_confirmed + LAPLACE_ALPHA * 2)
            fp_rate = (fp + LAPLACE_ALPHA) / (total_denied + LAPLACE_ALPHA * 2)

            lr = tp_rate / fp_rate if fp_rate > 0 else 1.0
            stats.likelihood_ratio = round(lr, 3)
            stats.true_positive_rate = round(tp_rate, 4)
            stats.base_rate = round(tp_rate, 4)  # Store the smoothed rate

    priors = PriorTables(
        feature_priors=feature_priors,
        global_base_rate=round(global_base_rate, 4),
        last_updated=date.today(),
        total_labeled_rumors=total_resolved,
    )

    logger.info(
        f"Built prior tables: base_rate={global_base_rate:.3f}, "
        f"{total_resolved} resolved ({total_confirmed} confirmed, {total_denied} denied)"
    )
    return priors


def _count_feature(
    feature_priors: Dict[str, Dict[str, FeatureStats]],
    dimension: str,
    value: str,
    is_true: bool,
):
    """Increment feature counts (using FeatureStats fields temporarily)."""
    if value not in feature_priors[dimension]:
        feature_priors[dimension][value] = FeatureStats(
            base_rate=0, true_positive_rate=0, sample_size=0
        )
    stats = feature_priors[dimension][value]
    stats.sample_size += 1
    if is_true:
        stats.true_positive_rate = (stats.true_positive_rate or 0) + 1  # TP count
    else:
        stats.base_rate = (stats.base_rate or 0) + 1  # FP count


# ──────────────────────────────────────────────
# Scoring
# ──────────────────────────────────────────────

def score_rumor(
    features: Dict[str, Any],
    prior_tables: PriorTables,
    author_track_record: str = "no_history",
    source_platform: str = "",
    corroboration_count: int = 0,
) -> Tuple[float, ConfidenceTier, str]:
    """Score a single rumor using Bayesian posterior probability.

    Returns:
        (score, confidence_tier, explanation)
    """
    base_rate = prior_tables.global_base_rate
    prior_odds = base_rate / (1 - base_rate) if base_rate < 1.0 else 10.0

    odds = prior_odds
    explanations = []

    # Apply each feature dimension's likelihood ratio
    for dimension in FEATURE_DIMENSIONS:
        dim_priors = prior_tables.feature_priors.get(dimension, {})
        if not dim_priors:
            continue

        # Get the feature value
        if dimension == "source_platform":
            value = source_platform
        elif dimension == "author_track_record":
            value = author_track_record
        elif dimension == "corroboration_count":
            value = str(min(corroboration_count, 3)) if corroboration_count < 3 else "3+"
        else:
            value = features.get(dimension, "")

        if not value or value not in dim_priors:
            continue

        stats = dim_priors[value]
        lr = stats.likelihood_ratio

        # Discount LR for low sample sizes (shrink toward 1.0)
        if stats.sample_size < 10:
            shrinkage = stats.sample_size / 10.0
            lr = 1.0 + (lr - 1.0) * shrinkage

        odds *= lr

        if abs(lr - 1.0) > 0.1:
            direction = "+" if lr > 1.0 else "-"
            explanations.append(f"{dimension}={value} ({direction}{lr:.1f}x)")

    # Convert odds back to probability
    posterior = odds / (1 + odds)
    posterior = max(0.0, min(1.0, posterior))

    # Determine confidence tier
    tier = ConfidenceTier.NOISE
    if posterior >= TIER_THRESHOLDS[ConfidenceTier.HIGH]:
        tier = ConfidenceTier.HIGH
    elif posterior >= TIER_THRESHOLDS[ConfidenceTier.MEDIUM]:
        tier = ConfidenceTier.MEDIUM
    elif posterior >= TIER_THRESHOLDS[ConfidenceTier.LOW]:
        tier = ConfidenceTier.LOW

    explanation = " | ".join(explanations) if explanations else "No strong signals"

    return round(posterior, 3), tier, explanation


def score_clusters(
    clusters: List[Dict[str, Any]],
    rumor_records: List[Dict[str, Any]],
    prior_tables: PriorTables,
    author_records: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Score all clusters using their constituent rumors' features."""
    rumor_lookup = {r.get("id", ""): r for r in rumor_records}
    scored = []

    for cluster in clusters:
        # Aggregate features from constituent rumors
        rids = cluster.get("rumor_ids", [])
        agg_features = _aggregate_cluster_features(rids, rumor_lookup)

        # Get best author track record
        best_track = "no_history"
        if author_records:
            for rid in rids:
                rumor = rumor_lookup.get(rid, {})
                author = rumor.get("author", "")
                if author in author_records:
                    track = _get_track_record(author_records[author])
                    if track == "previously_correct":
                        best_track = track
                        break
                    elif track == "mixed" and best_track == "no_history":
                        best_track = track

        # Get source platform (most common sub)
        platform = _most_common_platform(rids, rumor_lookup)

        # Score
        score, tier, explanation = score_rumor(
            features=agg_features,
            prior_tables=prior_tables,
            author_track_record=best_track,
            source_platform=platform,
            corroboration_count=cluster.get("independent_source_count", 0),
        )

        cluster_scored = dict(cluster)
        cluster_scored["score"] = score
        cluster_scored["confidence_tier"] = tier.value
        cluster_scored["score_explanation"] = explanation
        scored.append(cluster_scored)

    # Sort by score descending
    scored.sort(key=lambda c: c.get("score", 0), reverse=True)

    logger.info(f"Scored {len(scored)} clusters")
    return scored


def _aggregate_cluster_features(
    rumor_ids: List[str],
    rumor_lookup: Dict[str, Dict],
) -> Dict[str, str]:
    """Aggregate features across rumors in a cluster (take most specific)."""
    # Specificity priority order
    spec_order = [
        "exact_name_or_location", "city_level", "region_level",
        "category_only", "vague"
    ]
    source_order = [
        "insider_named", "insider_family", "insider_anonymous",
        "secondhand", "speculation", "prediction"
    ]

    best = {}
    for rid in rumor_ids:
        rumor = rumor_lookup.get(rid, {})
        features = rumor.get("features", {})

        # Take most common category
        cat = features.get("category", "other")
        best.setdefault("category", cat)

        # Take most specific specificity
        spec = features.get("specificity", "vague")
        if spec in spec_order:
            cur = best.get("specificity", "vague")
            if spec_order.index(spec) < spec_order.index(cur):
                best["specificity"] = spec

        # Take strongest source type
        src = features.get("claimed_source_type", "speculation")
        if src in source_order:
            cur = best.get("claimed_source_type", "speculation")
            if source_order.index(src) < source_order.index(cur):
                best["claimed_source_type"] = src

    return best


def _most_common_platform(
    rumor_ids: List[str],
    rumor_lookup: Dict[str, Dict],
) -> str:
    """Get the most common source sub from a cluster's rumors."""
    counts: Dict[str, int] = {}
    for rid in rumor_ids:
        rumor = rumor_lookup.get(rid, {})
        sub = rumor.get("source_sub", "")
        if sub:
            counts[sub] = counts.get(sub, 0) + 1
    return max(counts, key=counts.get) if counts else ""


def _get_track_record(author_data: Dict) -> str:
    total = author_data.get("total_predictions", 0)
    if total == 0:
        return "no_history"
    ratio = author_data.get("correct_predictions", 0) / total
    if ratio >= 0.6:
        return "previously_correct"
    elif ratio <= 0.3:
        return "previously_wrong"
    return "mixed"


# ──────────────────────────────────────────────
# Prior Table Updates (Incremental)
# ──────────────────────────────────────────────

def update_priors(
    prior_tables: PriorTables,
    new_resolutions: List[Dict[str, Any]],
    rumor_records: List[Dict[str, Any]],
) -> PriorTables:
    """Incrementally update prior tables with newly resolved rumors."""
    if not new_resolutions:
        return prior_tables

    rumor_lookup = {r.get("id", ""): r for r in rumor_records}
    new_confirmed = 0
    new_denied = 0

    for cluster in new_resolutions:
        status = cluster.get("resolution", {}).get("status", "unresolved")
        is_true = status in ("confirmed", "partially_confirmed")
        is_false = status == "denied"

        if not is_true and not is_false:
            continue

        if is_true:
            new_confirmed += 1
        else:
            new_denied += 1

        # Update feature counts for each rumor in this cluster
        for rid in cluster.get("rumor_ids", []):
            rumor = rumor_lookup.get(rid, {})
            features = rumor.get("features", {})

            for dimension in FEATURE_DIMENSIONS:
                if dimension == "source_platform":
                    value = rumor.get("source_sub", "")
                elif dimension == "corroboration_count":
                    corr = features.get("corroboration_count", 0)
                    value = str(min(corr, 3)) if corr < 3 else "3+"
                elif dimension == "author_track_record":
                    continue  # Updated separately
                else:
                    value = features.get(dimension, "")

                if not value:
                    continue

                dim_priors = prior_tables.feature_priors.setdefault(dimension, {})
                if value not in dim_priors:
                    dim_priors[value] = FeatureStats()

                stats = dim_priors[value]
                stats.sample_size += 1
                # Recompute LR with updated counts (simplified incremental update)

    # Update global stats
    old_total = prior_tables.total_labeled_rumors
    new_total = old_total + new_confirmed + new_denied
    if new_total > 0:
        old_confirmed = prior_tables.global_base_rate * old_total
        prior_tables.global_base_rate = round(
            (old_confirmed + new_confirmed) / new_total, 4
        )
    prior_tables.total_labeled_rumors = new_total
    prior_tables.last_updated = date.today()

    logger.info(
        f"Updated priors: +{new_confirmed} confirmed, +{new_denied} denied "
        f"(total: {new_total})"
    )
    return prior_tables


# ──────────────────────────────────────────────
# Calibration
# ──────────────────────────────────────────────

def calibration_check(
    scored_clusters: List[Dict[str, Any]],
) -> CalibrationReport:
    """Check calibration: do predicted probabilities match actual outcomes?

    Buckets scores into deciles and compares predicted vs actual rates.
    """
    # Only use resolved clusters
    resolved = [
        c for c in scored_clusters
        if c.get("resolution", {}).get("status") in ("confirmed", "partially_confirmed", "denied")
    ]

    if not resolved:
        return CalibrationReport(notes=["No resolved clusters for calibration"])

    deciles = []
    for i in range(10):
        low = i / 10.0
        high = (i + 1) / 10.0

        bucket = [
            c for c in resolved
            if low <= c.get("score", 0) < high
        ]

        if not bucket:
            deciles.append(DecileBucket(
                range_low=low, range_high=high,
                count=0, actual_true_rate=0, predicted_avg=0, deviation=0,
            ))
            continue

        actual_true = sum(
            1 for c in bucket
            if c.get("resolution", {}).get("status") in ("confirmed", "partially_confirmed")
        )
        actual_rate = actual_true / len(bucket)
        predicted_avg = sum(c.get("score", 0) for c in bucket) / len(bucket)
        deviation = actual_rate - predicted_avg

        deciles.append(DecileBucket(
            range_low=low,
            range_high=high,
            count=len(bucket),
            actual_true_rate=round(actual_rate, 3),
            predicted_avg=round(predicted_avg, 3),
            deviation=round(deviation, 3),
        ))

    # Overall accuracy
    total_correct = sum(
        1 for c in resolved
        if (c.get("score", 0) >= 0.5) == (c.get("resolution", {}).get("status") in ("confirmed", "partially_confirmed"))
    )
    overall_accuracy = total_correct / len(resolved) if resolved else 0

    # Check if retrain needed (>15% deviation in any non-empty decile)
    needs_retrain = any(
        abs(d.deviation) > 0.15 and d.count >= 5
        for d in deciles
    )

    notes = []
    if needs_retrain:
        notes.append("Calibration off by >15% in one or more deciles — consider retraining")

    report = CalibrationReport(
        total_scored=len(scored_clusters),
        total_resolved=len(resolved),
        deciles=deciles,
        overall_accuracy=round(overall_accuracy, 3),
        needs_retrain=needs_retrain,
        notes=notes,
    )

    logger.info(
        f"Calibration: accuracy={overall_accuracy:.3f}, "
        f"needs_retrain={needs_retrain}, resolved={len(resolved)}"
    )
    return report


# ──────────────────────────────────────────────
# Persistence
# ──────────────────────────────────────────────

def save_prior_tables(tables: PriorTables, path: str):
    """Save prior tables to JSON."""
    atomic_write_json(path, tables.model_dump(mode="json"))


def load_prior_tables(path: str) -> Optional[PriorTables]:
    """Load prior tables from JSON."""
    data = load_json(path, default=None)
    if data is None:
        return None
    try:
        return PriorTables(**data)
    except Exception as e:
        logger.error(f"Failed to load prior tables from {path}: {e}")
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build or check Bayesian scoring")
    parser.add_argument("command", choices=["build", "calibrate", "score"])
    parser.add_argument("--matched", default="data/matched_dataset.json")
    parser.add_argument("--rumors", default="data/classified_rumors.json")
    parser.add_argument("--priors", default="data/prior_tables.json")
    parser.add_argument("--output", default="data/calibration_report.json")
    args = parser.parse_args()

    from engines.logging_config import setup_logging
    setup_logging("INFO")

    if args.command == "build":
        clusters = load_json(args.matched)
        rumors = load_json(args.rumors)
        tables = build_prior_tables(clusters, rumors)
        save_prior_tables(tables, args.priors)
        print(f"Built prior tables -> {args.priors}")
        print(f"  Global base rate: {tables.global_base_rate}")
        print(f"  Total labeled: {tables.total_labeled_rumors}")

    elif args.command == "calibrate":
        scored = load_json(args.matched)
        report = calibration_check(scored)
        atomic_write_json(args.output, report.model_dump(mode="json"))
        print(f"Calibration report -> {args.output}")
        print(f"  Overall accuracy: {report.overall_accuracy}")
        print(f"  Needs retrain: {report.needs_retrain}")

    elif args.command == "score":
        clusters = load_json(args.matched)
        rumors = load_json(args.rumors)
        tables = load_prior_tables(args.priors)
        if not tables:
            print("No prior tables found — run 'build' first")
            sys.exit(1)
        scored = score_clusters(clusters, rumors, tables)
        for c in scored[:10]:
            print(f"  {c.get('score', 0):.3f} [{c.get('confidence_tier')}] {c.get('cluster_summary', '')[:60]}")
