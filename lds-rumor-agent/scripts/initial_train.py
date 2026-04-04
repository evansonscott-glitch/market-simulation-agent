#!/usr/bin/env python3
"""
One-Time Phase 1 Training Pipeline

Runs the full historical pipeline:
  1. Scrape newsroom for ground truth (12 months)
  2. Scrape Reddit history via Arctic Shift (12 months)
  3. Filter to candidates
  4. Classify rumors via Claude
  5. Cluster corroborating rumors
  6. Match clusters to ground truth outcomes
  7. Build Bayesian prior tables
  8. Run calibration check

Usage:
    python3 scripts/initial_train.py [--dry-run] [--lookback 12]
"""
import os
import sys
import argparse
from pathlib import Path

# Setup paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
REPO_DIR = os.path.dirname(PROJECT_DIR)
sys.path.insert(0, REPO_DIR)
sys.path.insert(0, PROJECT_DIR)

from engines.logging_config import setup_logging, get_logger
from scrapers.newsroom_scraper import scrape_ground_truth
from scrapers.reddit_scraper import scrape_reddit
from scrapers.utils import ensure_data_dir, load_json
from rumor_engine.classifier import classify_candidates
from rumor_engine.clusterer import cluster_rumors
from rumor_engine.matcher import match_clusters
from rumor_engine.scorer import (
    build_prior_tables, save_prior_tables, score_clusters,
    calibration_check,
)

logger = get_logger("scripts.initial_train")


def main():
    parser = argparse.ArgumentParser(description="Run Phase 1 training pipeline")
    parser.add_argument("--lookback", type=int, default=12, help="Months to look back")
    parser.add_argument("--model", default="claude-sonnet-4-6", help="Claude model for classification")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true", help="Skip Claude API calls, use sample data")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--data-dir", default=os.path.join(PROJECT_DIR, "data"))
    args = parser.parse_args()

    setup_logging(args.log_level)
    data_dir = ensure_data_dir(args.data_dir)

    logger.info("=" * 60)
    logger.info("PHASE 1: INITIAL TRAINING PIPELINE")
    logger.info(f"  Lookback: {args.lookback} months")
    logger.info(f"  Model: {args.model}")
    logger.info(f"  Data dir: {data_dir}")
    logger.info("=" * 60)

    # ── Step 1: Ground Truth ──
    logger.info("\n[1/7] Scraping ground truth from newsroom...")
    gt_path = os.path.join(data_dir, "ground_truth.json")
    ground_truth = scrape_ground_truth(
        lookback_months=args.lookback,
        output_path=gt_path,
    )
    logger.info(f"  -> {len(ground_truth)} announcements")

    # ── Step 2: Reddit Historical ──
    logger.info("\n[2/7] Scraping Reddit history via Arctic Shift...")
    candidates_path = os.path.join(data_dir, "reddit_candidates.json")
    candidates = scrape_reddit(
        mode="historical",
        lookback_months=args.lookback,
        output_raw=os.path.join(data_dir, "reddit_raw.json"),
        output_candidates=candidates_path,
    )
    logger.info(f"  -> {len(candidates)} candidate posts")

    if not candidates:
        logger.error("No candidates found — check Reddit scraper")
        return

    # ── Step 3: Classify ──
    logger.info("\n[3/7] Classifying rumors via Claude...")
    classified_path = os.path.join(data_dir, "classified_rumors.json")
    if args.dry_run:
        logger.info("  DRY RUN — skipping Claude classification")
        classified = load_json(classified_path, default=[])
    else:
        classified_records = classify_candidates(
            candidates, model=args.model, batch_size=args.batch_size,
            output_path=classified_path,
        )
        classified = [r.model_dump(mode="json") for r in classified_records]
    logger.info(f"  -> {len(classified)} classified rumors")

    if not classified:
        logger.error("No rumors classified — check classifier")
        return

    # ── Step 4: Cluster ──
    logger.info("\n[4/7] Clustering corroborating rumors...")
    clusters_path = os.path.join(data_dir, "rumor_clusters.json")
    if args.dry_run:
        logger.info("  DRY RUN — skipping Claude clustering")
        clusters = load_json(clusters_path, default=[])
    else:
        cluster_records = cluster_rumors(
            classified, model=args.model, output_path=clusters_path,
        )
        clusters = [c.model_dump(mode="json") for c in cluster_records]
    logger.info(f"  -> {len(clusters)} clusters")

    # ── Step 5: Match ──
    logger.info("\n[5/7] Matching clusters to ground truth...")
    matched_path = os.path.join(data_dir, "matched_dataset.json")
    gt_dicts = [g.model_dump(mode="json") for g in ground_truth] if ground_truth else load_json(gt_path, default=[])
    if args.dry_run:
        logger.info("  DRY RUN — skipping Claude matching")
        matched = load_json(matched_path, default=[])
    else:
        matched = match_clusters(
            clusters, gt_dicts, model=args.model, output_path=matched_path,
        )
    logger.info(f"  -> {len(matched)} matched clusters")

    # ── Step 6: Build Priors ──
    logger.info("\n[6/7] Building Bayesian prior tables...")
    priors_path = os.path.join(data_dir, "prior_tables.json")
    tables = build_prior_tables(matched, classified)
    save_prior_tables(tables, priors_path)
    logger.info(f"  -> Base rate: {tables.global_base_rate:.3f}")
    logger.info(f"  -> Total labeled: {tables.total_labeled_rumors}")

    # ── Step 7: Calibration ──
    logger.info("\n[7/7] Running calibration check...")
    scored = score_clusters(matched, classified, tables)
    report = calibration_check(scored)

    report_path = os.path.join(data_dir, "calibration_report.json")
    from scrapers.utils import atomic_write_json
    atomic_write_json(report_path, report.model_dump(mode="json"))

    logger.info(f"  -> Overall accuracy: {report.overall_accuracy}")
    logger.info(f"  -> Needs retrain: {report.needs_retrain}")

    # Save scored clusters as initial open_rumors
    from scrapers.utils import atomic_write_json
    open_path = os.path.join(data_dir, "open_rumors.json")
    open_rumors = [c for c in scored if c.get("resolution", {}).get("status") == "unresolved"]
    atomic_write_json(open_path, open_rumors)

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("TRAINING COMPLETE")
    logger.info(f"  Announcements:      {len(ground_truth)}")
    logger.info(f"  Reddit candidates:  {len(candidates)}")
    logger.info(f"  Classified rumors:  {len(classified)}")
    logger.info(f"  Clusters:           {len(clusters)}")
    logger.info(f"  Labeled (matched):  {len(matched)}")
    logger.info(f"  Open (unresolved):  {len(open_rumors)}")
    logger.info(f"  Accuracy:           {report.overall_accuracy:.3f}")
    logger.info(f"  Base rate:          {tables.global_base_rate:.3f}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
