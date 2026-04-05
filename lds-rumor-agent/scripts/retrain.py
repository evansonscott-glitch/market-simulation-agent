#!/usr/bin/env python3
"""
Retrain: Recompute all priors from the full labeled dataset.

Use when calibration has drifted or after adding significant new data.
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_DIR)

from lib.logging_config import setup_logging, get_logger
from scrapers.utils import load_json, atomic_write_json
from rumor_engine.scorer import (
    build_prior_tables, save_prior_tables, load_prior_tables,
    score_clusters, calibration_check,
)

logger = get_logger("scripts.retrain")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Retrain prior tables from full dataset")
    parser.add_argument("--data-dir", default=os.path.join(PROJECT_DIR, "data"))
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    setup_logging(args.log_level)
    data_dir = args.data_dir

    # Load all data
    matched = load_json(os.path.join(data_dir, "matched_dataset.json"), default=[])
    open_rumors = load_json(os.path.join(data_dir, "open_rumors.json"), default=[])
    all_rumors = load_json(os.path.join(data_dir, "classified_rumors.json"), default=[])
    author_records = load_json(os.path.join(data_dir, "author_records.json"), default={})

    # Combine all resolved clusters
    all_resolved = []
    for cluster in matched + open_rumors:
        if cluster.get("resolution", {}).get("status", "unresolved") != "unresolved":
            all_resolved.append(cluster)

    logger.info(f"Retraining from {len(all_resolved)} resolved clusters, {len(all_rumors)} rumors")

    # Build new tables
    tables = build_prior_tables(all_resolved, all_rumors, author_records)

    # Version bump
    old = load_prior_tables(os.path.join(data_dir, "prior_tables.json"))
    if old:
        ver = old.version
        if ver.startswith("v") and "." in ver:
            try:
                major, minor = ver[1:].split(".", 1)
                tables.version = f"v{major}.{int(minor) + 1}"
            except ValueError:
                tables.version = "v2.0"
    else:
        tables.version = "v1.0"

    save_prior_tables(tables, os.path.join(data_dir, "prior_tables.json"))

    # Re-score and check calibration
    scored = score_clusters(all_resolved, all_rumors, tables, author_records)
    report = calibration_check(scored)
    atomic_write_json(
        os.path.join(data_dir, "calibration_report.json"),
        report.model_dump(mode="json"),
    )

    logger.info(f"Retrain complete: version {tables.version}")
    logger.info(f"  Base rate: {tables.global_base_rate:.3f}")
    logger.info(f"  Accuracy: {report.overall_accuracy:.3f}")
    logger.info(f"  Needs retrain: {report.needs_retrain}")


if __name__ == "__main__":
    main()
