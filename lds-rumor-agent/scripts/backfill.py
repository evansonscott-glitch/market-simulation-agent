#!/usr/bin/env python3
"""
Backfill: Expand historical data by scraping additional time ranges or sources.
"""
import os
import sys
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_DIR)

from lib.logging_config import setup_logging, get_logger
from scrapers.reddit_scraper import scrape_historical_reddit, filter_candidates
from scrapers.newsroom_scraper import scrape_ground_truth
from scrapers.utils import load_json, atomic_write_json, ensure_data_dir

logger = get_logger("scripts.backfill")


def main():
    parser = argparse.ArgumentParser(description="Backfill historical data")
    parser.add_argument("--source", choices=["reddit", "newsroom", "both"], default="both")
    parser.add_argument("--lookback", type=int, default=24, help="Months to look back")
    parser.add_argument("--data-dir", default=os.path.join(PROJECT_DIR, "data"))
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    setup_logging(args.log_level)
    data_dir = ensure_data_dir(args.data_dir)

    if args.source in ("newsroom", "both"):
        logger.info(f"Backfilling newsroom ({args.lookback} months)")
        existing_gt = load_json(os.path.join(data_dir, "ground_truth.json"), default=[])
        existing_ids = {a.get("id") for a in existing_gt}

        new_gt = scrape_ground_truth(lookback_months=args.lookback)
        new_gt_dicts = [g.model_dump(mode="json") for g in new_gt]

        added = [g for g in new_gt_dicts if g.get("id") not in existing_ids]
        if added:
            existing_gt.extend(added)
            atomic_write_json(os.path.join(data_dir, "ground_truth.json"), existing_gt)
            logger.info(f"  Added {len(added)} new announcements (total: {len(existing_gt)})")
        else:
            logger.info("  No new announcements found")

    if args.source in ("reddit", "both"):
        logger.info(f"Backfilling Reddit ({args.lookback} months)")
        existing_raw = load_json(os.path.join(data_dir, "reddit_raw.json"), default=[])
        existing_ids = {p.get("id") for p in existing_raw}

        new_raw = scrape_historical_reddit(lookback_months=args.lookback)
        added = [p for p in new_raw if p.get("id") not in existing_ids]

        if added:
            existing_raw.extend(added)
            atomic_write_json(os.path.join(data_dir, "reddit_raw.json"), existing_raw)

            # Re-filter candidates
            candidates = filter_candidates(
                existing_raw,
                output_path=os.path.join(data_dir, "reddit_candidates.json"),
            )
            logger.info(f"  Added {len(added)} new posts, {len(candidates)} total candidates")
        else:
            logger.info("  No new Reddit posts found")


if __name__ == "__main__":
    main()
