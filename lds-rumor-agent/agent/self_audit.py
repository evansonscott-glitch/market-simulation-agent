#!/usr/bin/env python3
"""
Component 6: Continuous Learning & Self-Audit

Monthly self-audit (first Saturday of each month):
  - Recompute full calibration report
  - Flag feature dimensions with significant drift
  - Trigger full retrain if accuracy degrades
"""
import os
import sys
from datetime import date
from typing import Dict, Any, List, Optional

from lib.logging_config import get_logger

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from models import PriorTables, CalibrationReport
from rumor_engine.scorer import (
    calibration_check, build_prior_tables, save_prior_tables, load_prior_tables,
)
from scrapers.utils import atomic_write_json, load_json

logger = get_logger("agent.self_audit")


def is_first_saturday_of_month() -> bool:
    """Check if today is the first Saturday of the month."""
    today = date.today()
    return today.weekday() == 5 and today.day <= 7


def maybe_run_monthly_audit(
    data_dir: str,
    prior_tables: PriorTables,
    scored_clusters: List[Dict[str, Any]],
    all_rumors: List[Dict[str, Any]],
):
    """Run monthly audit if it's the first Saturday."""
    if not is_first_saturday_of_month():
        return

    logger.info("=" * 40)
    logger.info("MONTHLY SELF-AUDIT")
    logger.info("=" * 40)

    run_full_audit(data_dir, prior_tables, scored_clusters, all_rumors)


def run_full_audit(
    data_dir: str,
    prior_tables: PriorTables,
    scored_clusters: List[Dict[str, Any]],
    all_rumors: List[Dict[str, Any]],
) -> CalibrationReport:
    """Full calibration audit."""
    # 1. Calibration check
    report = calibration_check(scored_clusters)

    # Save report
    report_path = os.path.join(data_dir, "calibration_report.json")
    atomic_write_json(report_path, report.model_dump(mode="json"))
    logger.info(f"Calibration report saved: accuracy={report.overall_accuracy}")

    # 2. Check for feature drift
    drift_notes = check_feature_drift(prior_tables, data_dir)
    if drift_notes:
        report.notes.extend(drift_notes)
        atomic_write_json(report_path, report.model_dump(mode="json"))

    # 3. Full retrain if needed
    if report.needs_retrain:
        logger.warning("Calibration degraded — triggering full retrain")
        retrain(data_dir, all_rumors)

    # 4. Archive prior table version
    archive_priors(data_dir, prior_tables)

    return report


def check_feature_drift(
    prior_tables: PriorTables,
    data_dir: str,
) -> List[str]:
    """Check if any feature dimensions have drifted significantly."""
    notes = []

    # Load previous calibration for comparison
    prev_path = os.path.join(data_dir, "calibration_report_prev.json")
    prev_data = load_json(prev_path, default=None)
    if prev_data is None:
        return notes

    try:
        prev_report = CalibrationReport(**prev_data)
    except Exception:
        return notes

    # Compare decile deviations
    current_report = calibration_check(
        load_json(os.path.join(data_dir, "open_rumors.json"), default=[])
    )

    for i, (cur, prev) in enumerate(zip(current_report.deciles, prev_report.deciles)):
        if cur.count < 5 or prev.count < 5:
            continue
        drift = abs(cur.deviation - prev.deviation)
        if drift > 0.10:
            notes.append(
                f"Decile {i} drift: deviation changed by {drift:.2f} "
                f"({prev.deviation:.2f} -> {cur.deviation:.2f})"
            )

    # Check for stale feature dimensions
    for dimension, values in prior_tables.feature_priors.items():
        total_samples = sum(s.sample_size for s in values.values())
        if total_samples < 5:
            notes.append(f"Feature dimension '{dimension}' has very few samples ({total_samples})")

    if notes:
        logger.warning(f"Feature drift detected: {len(notes)} issues")
        for note in notes:
            logger.warning(f"  {note}")

    return notes


def retrain(data_dir: str, all_rumors: List[Dict[str, Any]]):
    """Full retrain: recompute all priors from the entire labeled dataset."""
    logger.info("Starting full retrain from labeled dataset")

    matched = load_json(os.path.join(data_dir, "matched_dataset.json"), default=[])
    open_rumrs = load_json(os.path.join(data_dir, "open_rumors.json"), default=[])

    # Combine all resolved clusters
    all_resolved = []
    for cluster in matched + open_rumrs:
        if cluster.get("resolution", {}).get("status", "unresolved") != "unresolved":
            all_resolved.append(cluster)

    if not all_resolved:
        logger.warning("No resolved clusters for retrain")
        return

    author_records = load_json(os.path.join(data_dir, "author_records.json"), default={})

    new_tables = build_prior_tables(all_resolved, all_rumors, author_records)
    new_tables.version = _next_version(
        load_prior_tables(os.path.join(data_dir, "prior_tables.json"))
    )

    save_prior_tables(new_tables, os.path.join(data_dir, "prior_tables.json"))
    logger.info(f"Retrain complete: version {new_tables.version}")


def archive_priors(data_dir: str, tables: PriorTables):
    """Archive a copy of the current prior tables."""
    archive_dir = os.path.join(data_dir, "prior_archive")
    os.makedirs(archive_dir, exist_ok=True)

    today = date.today()
    path = os.path.join(archive_dir, f"prior_tables_{today.isoformat()}.json")
    atomic_write_json(path, tables.model_dump(mode="json"))

    # Keep only last 12 archives
    import glob
    archives = sorted(glob.glob(os.path.join(archive_dir, "prior_tables_*.json")))
    while len(archives) > 12:
        os.remove(archives.pop(0))


def _next_version(current: Optional[PriorTables]) -> str:
    """Increment the version string."""
    if current is None:
        return "v1.0"
    ver = current.version
    if ver.startswith("v") and "." in ver:
        try:
            major, minor = ver[1:].split(".", 1)
            return f"v{major}.{int(minor) + 1}"
        except ValueError:
            pass
    return "v1.0"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run self-audit")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--force", action="store_true", help="Run even if not first Saturday")
    args = parser.parse_args()

    from lib.logging_config import setup_logging
    setup_logging("INFO")

    data_dir = args.data_dir
    prior_tables = load_prior_tables(os.path.join(data_dir, "prior_tables.json"))
    if not prior_tables:
        print("No prior tables found")
        sys.exit(1)

    scored = load_json(os.path.join(data_dir, "open_rumors.json"), default=[])
    all_rumors = load_json(os.path.join(data_dir, "classified_rumors.json"), default=[])

    if args.force or is_first_saturday_of_month():
        report = run_full_audit(data_dir, prior_tables, scored, all_rumors)
        print(f"Audit complete: accuracy={report.overall_accuracy}, retrain={report.needs_retrain}")
    else:
        print("Not first Saturday — use --force to run anyway")
