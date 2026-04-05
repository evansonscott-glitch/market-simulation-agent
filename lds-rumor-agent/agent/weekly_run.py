#!/usr/bin/env python3
"""
Component 5: Weekly Pipeline Orchestrator

The main production cron job. Runs every Saturday morning.

Pipeline:
  1. Scrape Reddit (last 7 days)
  2. Classify and cluster new rumors
  3. Check new clusters against existing open rumors
  4. Score all new/updated clusters
  5. Scrape newsroom for new announcements
  6. Resolve open rumors against new announcements
  7. Update prior tables and author records
  8. Generate digest and send email
  9. Archive everything

Cron: 0 8 * * 6
"""
import os
import sys
import yaml
import json
from datetime import date, datetime, timedelta
from typing import Dict, Any, Optional
from pathlib import Path

# Setup paths
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(AGENT_DIR)
REPO_DIR = os.path.dirname(PROJECT_DIR)
sys.path.insert(0, REPO_DIR)
sys.path.insert(0, PROJECT_DIR)

from engines.logging_config import setup_logging, get_logger
from scrapers.reddit_scraper import scrape_reddit
from scrapers.newsroom_scraper import scrape_ground_truth
from scrapers.church_site_monitor import (
    run_site_monitor, match_changes_to_clusters, generate_standalone_signals,
)
from scrapers.utils import atomic_write_json, load_json, ensure_data_dir
from rumor_engine.classifier import classify_candidates
from rumor_engine.clusterer import cluster_rumors, update_clusters_with_new_rumors
from rumor_engine.scorer import (
    score_clusters, load_prior_tables, save_prior_tables,
    update_priors, calibration_check,
)
from rumor_engine.resolver import resolve_rumors, check_stale_rumors
from agent.digest_generator import generate_and_send_digest
from agent.self_audit import maybe_run_monthly_audit

logger = get_logger("agent.weekly")


def load_config() -> Dict[str, Any]:
    """Load config from YAML + environment variables."""
    config_path = os.path.join(PROJECT_DIR, "config", "config.yaml")

    config = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}

    # Environment overrides
    config.setdefault("anthropic_api_key", os.environ.get("ANTHROPIC_API_KEY", ""))
    config.setdefault("llm_model", "claude-sonnet-4-6")

    reddit = config.setdefault("reddit", {})
    reddit.setdefault("client_id", os.environ.get("REDDIT_CLIENT_ID", ""))
    reddit.setdefault("client_secret", os.environ.get("REDDIT_CLIENT_SECRET", ""))
    reddit.setdefault("user_agent", os.environ.get("REDDIT_USER_AGENT", "lds-rumor-agent/1.0"))

    email = config.setdefault("email", {})
    email.setdefault("sender_address", os.environ.get("GMAIL_ADDRESS", ""))
    email.setdefault("app_password", os.environ.get("GMAIL_APP_PASSWORD", ""))
    email.setdefault("recipient", os.environ.get("DIGEST_RECIPIENT", ""))

    config.setdefault("data_dir", os.path.join(PROJECT_DIR, "data"))
    config.setdefault("site_monitor", {
        "enabled": True,
        "snapshot_dir": os.path.join(PROJECT_DIR, "data", "site_snapshots"),
    })

    return config


def weekly_run(config: Optional[Dict[str, Any]] = None, dry_run: bool = False):
    """Execute the full weekly pipeline."""
    if config is None:
        config = load_config()

    data_dir = ensure_data_dir(config["data_dir"])
    model = config.get("llm_model", "claude-sonnet-4-6")
    reddit_cfg = config.get("reddit", {})
    email_cfg = config.get("email", {})
    site_cfg = config.get("site_monitor", {})

    # Set ANTHROPIC_API_KEY if provided
    if config.get("anthropic_api_key"):
        os.environ["ANTHROPIC_API_KEY"] = config["anthropic_api_key"]

    logger.info("=" * 60)
    logger.info(f"WEEKLY RUN — {date.today()}")
    logger.info("=" * 60)

    # Load existing data
    open_clusters = load_json(os.path.join(data_dir, "open_rumors.json"), default=[])
    all_rumors = load_json(os.path.join(data_dir, "classified_rumors.json"), default=[])
    author_records = load_json(os.path.join(data_dir, "author_records.json"), default={})
    prior_tables = load_prior_tables(os.path.join(data_dir, "prior_tables.json"))

    if prior_tables is None:
        logger.error("No prior tables found. Run initial_train.py first.")
        return

    # ── Step 1: Scrape Reddit (last 7 days) ──
    logger.info("Step 1: Scraping Reddit")
    candidates = scrape_reddit(
        mode="live",
        client_id=reddit_cfg.get("client_id", ""),
        client_secret=reddit_cfg.get("client_secret", ""),
        user_agent=reddit_cfg.get("user_agent", "lds-rumor-agent/1.0"),
        subreddits=reddit_cfg.get("subreddits"),
        days_back=7,
        keywords=reddit_cfg.get("speculative_keywords"),
        min_engagement=reddit_cfg.get("min_engagement_comments", 10),
        output_raw=os.path.join(data_dir, "reddit_weekly_raw.json"),
        output_candidates=os.path.join(data_dir, "reddit_weekly_candidates.json"),
    )
    logger.info(f"  Found {len(candidates)} candidate posts")

    if not candidates:
        logger.info("No candidates this week — skipping to resolution check")
        new_classified = []
        new_clusters = []
    else:
        # ── Step 2: Classify new rumors ──
        logger.info("Step 2: Classifying rumors")
        new_classified = classify_candidates(
            candidates, model=model, batch_size=config.get("batch_size", 50),
        )
        logger.info(f"  Classified {len(new_classified)} rumors")

        # Add to running total
        all_rumors.extend([r.model_dump(mode="json") for r in new_classified])
        atomic_write_json(os.path.join(data_dir, "classified_rumors.json"), all_rumors)

        # ── Step 3: Cluster new rumors + check against existing ──
        logger.info("Step 3: Clustering")
        new_rumors_dicts = [r.model_dump(mode="json") for r in new_classified]

        if open_clusters:
            open_clusters = update_clusters_with_new_rumors(
                open_clusters, new_rumors_dicts, model=model,
            )
        else:
            new_clusters = cluster_rumors(new_rumors_dicts, model=model)
            open_clusters.extend([c.model_dump(mode="json") for c in new_clusters])

    # ── Step 4: Church website change detection ──
    site_changes = []
    standalone_signals = []
    if site_cfg.get("enabled", True):
        logger.info("Step 4: Monitoring Church websites")
        from models import SiteMonitorConfig
        sm_config = SiteMonitorConfig(**site_cfg) if isinstance(site_cfg, dict) else SiteMonitorConfig()

        site_changes = run_site_monitor(
            monitored_pages=sm_config.monitored_pages,
            monitored_sitemaps=sm_config.monitored_sitemaps,
            snapshot_dir=sm_config.snapshot_dir or os.path.join(data_dir, "site_snapshots"),
            data_dir=data_dir,
        )
        logger.info(f"  Detected {len(site_changes)} site changes")

        if site_changes and open_clusters:
            # Match changes to existing clusters (boosts their scores)
            open_clusters = match_changes_to_clusters(
                site_changes, open_clusters, model=model,
            )

            # Generate standalone signals for unmatched changes
            standalone_signals = generate_standalone_signals(site_changes, model=model)
            if standalone_signals:
                logger.info(f"  Generated {len(standalone_signals)} standalone site signals")
    else:
        logger.info("Step 4: Site monitoring disabled — skipping")

    # ── Step 5: Score all open clusters ──
    logger.info("Step 5: Scoring")
    scored = score_clusters(open_clusters, all_rumors, prior_tables, author_records)
    open_clusters = scored

    # ── Step 6: Scrape newsroom for new announcements ──
    logger.info("Step 6: Checking newsroom")
    new_announcements = scrape_ground_truth(
        lookback_months=1,  # Only last month for weekly check
        output_path=os.path.join(data_dir, "ground_truth_weekly.json"),
    )
    new_ann_dicts = [a.model_dump(mode="json") for a in new_announcements]
    logger.info(f"  Found {len(new_ann_dicts)} recent announcements")

    # Merge with existing ground truth
    existing_gt = load_json(os.path.join(data_dir, "ground_truth.json"), default=[])
    existing_ids = {a.get("id") for a in existing_gt}
    truly_new = [a for a in new_ann_dicts if a.get("id") not in existing_ids]
    if truly_new:
        existing_gt.extend(truly_new)
        atomic_write_json(os.path.join(data_dir, "ground_truth.json"), existing_gt)
        logger.info(f"  Added {len(truly_new)} new announcements to ground truth")

    # ── Step 7: Resolve open rumors ──
    logger.info("Step 7: Resolving rumors")
    open_clusters, newly_resolved, author_records = resolve_rumors(
        open_clusters, truly_new, all_rumors, author_records, model=model,
    )

    # Check for stale rumors (>6 months)
    open_clusters = check_stale_rumors(open_clusters)

    # ── Step 8: Update priors and save state ──
    logger.info("Step 8: Updating priors")
    if newly_resolved:
        prior_tables = update_priors(prior_tables, newly_resolved, all_rumors)
        save_prior_tables(prior_tables, os.path.join(data_dir, "prior_tables.json"))

    atomic_write_json(os.path.join(data_dir, "open_rumors.json"), open_clusters)
    atomic_write_json(os.path.join(data_dir, "author_records.json"), author_records)

    # ── Step 9: Generate and send digest ──
    logger.info("Step 9: Generating digest")

    # Combine scored clusters with standalone site signals
    new_this_week = [c for c in open_clusters if c.get("score") is not None]
    if standalone_signals:
        new_this_week.extend(standalone_signals)
    new_this_week.sort(key=lambda c: c.get("score", 0), reverse=True)

    still_watching = [
        c for c in open_clusters
        if c.get("resolution", {}).get("status", "unresolved") == "unresolved"
    ]
    still_watching.sort(key=lambda c: c.get("score", 0), reverse=True)

    model_stats = {
        "total_tracked": len(open_clusters),
        "resolved_this_week": len(newly_resolved),
        "accuracy_last_30_days": None,
        "prior_tables_version": prior_tables.version,
        "site_changes_detected": len(site_changes),
        "site_corroborations": sum(
            1 for c in open_clusters if c.get("has_site_corroboration")
        ),
    }

    if dry_run:
        logger.info("DRY RUN — skipping email")
        logger.info(f"  New rumors: {len(new_this_week)}")
        logger.info(f"  Resolved: {len(newly_resolved)}")
        logger.info(f"  Still watching: {len(still_watching)}")
        logger.info(f"  Site changes: {len(site_changes)}")
        logger.info(f"  Standalone site signals: {len(standalone_signals)}")
    else:
        sent = generate_and_send_digest(
            new_scored=new_this_week[:20],
            resolved=newly_resolved,
            still_watching=still_watching[:10],
            model_stats=model_stats,
            email_config=email_cfg,
            model=model,
            archive_dir=os.path.join(data_dir, "digests"),
        )
        if sent:
            logger.info("Digest sent successfully!")
        else:
            logger.error("Failed to send digest")

    # ── Step 10: Monthly audit check ──
    maybe_run_monthly_audit(
        data_dir=data_dir,
        prior_tables=prior_tables,
        scored_clusters=open_clusters,
        all_rumors=all_rumors,
    )

    logger.info("=" * 60)
    logger.info("WEEKLY RUN COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run weekly LDS rumor pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Skip email delivery")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--config", help="Path to config.yaml")
    args = parser.parse_args()

    setup_logging(args.log_level)

    config = None
    if args.config:
        with open(args.config) as f:
            config = yaml.safe_load(f)

    weekly_run(config=config, dry_run=args.dry_run)
