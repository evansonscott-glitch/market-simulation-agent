#!/usr/bin/env python3
"""
Component 3c: Claude-Powered Outcome Matcher

Matches rumor clusters to official announcements to determine which
rumors came true. Produces the labeled training dataset.

Output: data/matched_dataset.json
"""
import os
import sys
import json
from datetime import date, datetime
from typing import List, Dict, Any, Optional

from lib.llm_client import chat_completion
from lib.json_parser import parse_llm_json
from lib.logging_config import get_logger

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from models import (
    RumorCluster, AnnouncementRecord, RumorResolution,
    ResolutionStatus, MatchQuality,
)
from scrapers.utils import atomic_write_json, load_json

logger = get_logger("rumor_engine.matcher")


def _load_prompt() -> str:
    """Load the matching prompt template."""
    prompt_path = os.path.join(
        os.path.dirname(__file__), "..", "config", "prompts", "match.txt"
    )
    with open(prompt_path, "r") as f:
        return f.read()


def _format_ground_truth(announcements: List[Dict[str, Any]]) -> str:
    """Format announcements for the matching prompt."""
    lines = []
    for ann in announcements:
        aid = ann.get("id", "")
        ann_date = ann.get("date", "")
        title = ann.get("title", "")
        summary = ann.get("summary", "")[:200]
        category = ann.get("category", "")
        loc = ann.get("location", {})
        loc_str = ""
        if isinstance(loc, dict):
            parts = [loc.get("city", ""), loc.get("state", ""), loc.get("country", "")]
            loc_str = ", ".join(p for p in parts if p)

        lines.append(
            f"[{aid}] {ann_date} | {category} | {title}"
            + (f" | Location: {loc_str}" if loc_str else "")
            + (f" | {summary}" if summary != title else "")
        )
    return "\n".join(lines)


def _format_clusters(clusters: List[Dict[str, Any]]) -> str:
    """Format clusters for the matching prompt."""
    lines = []
    for c in clusters:
        cid = c.get("cluster_id", "")
        summary = c.get("cluster_summary", "")
        earliest = c.get("earliest_post_date", "")
        sources = c.get("independent_source_count", 0)

        lines.append(
            f"[{cid}] (earliest: {earliest}, sources: {sources}): {summary}"
        )
    return "\n".join(lines)


def match_batch(
    clusters: List[Dict[str, Any]],
    ground_truth: List[Dict[str, Any]],
    model: str = "claude-sonnet-4-6",
) -> List[Dict[str, Any]]:
    """Match a batch of clusters against ground truth."""
    prompt_template = _load_prompt()

    gt_text = _format_ground_truth(ground_truth)
    cluster_text = _format_clusters(clusters)

    # Fill in the template placeholders
    filled = prompt_template.replace("{ground_truth}", gt_text).replace("{clusters}", cluster_text)

    messages = [
        {"role": "user", "content": filled},
    ]

    response = chat_completion(
        messages=messages,
        model=model,
        temperature=0.2,
        max_tokens=8192,
    )

    parsed = parse_llm_json(response, expected_type=list, context="match_batch")
    return parsed


def match_clusters(
    clusters: List[Dict[str, Any]],
    ground_truth: List[Dict[str, Any]],
    model: str = "claude-sonnet-4-6",
    batch_size: int = 50,
    output_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Match all clusters against ground truth, with batching."""
    all_matches = []

    for i in range(0, len(clusters), batch_size):
        batch = clusters[i:i + batch_size]
        batch_num = i // batch_size + 1
        total = (len(clusters) + batch_size - 1) // batch_size
        logger.info(f"Matching batch {batch_num}/{total} ({len(batch)} clusters)")

        try:
            matches = match_batch(batch, ground_truth, model)
            all_matches.extend(matches)
        except Exception as e:
            logger.error(f"Matching batch {batch_num} failed: {e}")
            continue

    # Apply match results back to clusters
    match_lookup = {m.get("cluster_id", ""): m for m in all_matches}
    labeled_clusters = []

    for cluster in clusters:
        cid = cluster.get("cluster_id", "")
        match = match_lookup.get(cid, {})

        resolution = {
            "status": match.get("resolution_status", "unresolved"),
            "matched_announcement_id": match.get("matched_announcement_id"),
            "match_quality": match.get("match_quality", "no_match"),
            "days_before_announcement": match.get("days_before_announcement"),
        }

        # If resolved, add resolved_date
        if resolution["status"] in ("confirmed", "partially_confirmed", "denied"):
            ann_id = resolution["matched_announcement_id"]
            if ann_id:
                ann = next((a for a in ground_truth if a.get("id") == ann_id), None)
                if ann:
                    resolution["resolved_date"] = ann.get("date")

        cluster_copy = dict(cluster)
        cluster_copy["resolution"] = resolution
        labeled_clusters.append(cluster_copy)

    # Stats
    resolved = sum(1 for c in labeled_clusters if c.get("resolution", {}).get("status") != "unresolved")
    confirmed = sum(1 for c in labeled_clusters if c.get("resolution", {}).get("status") == "confirmed")
    logger.info(
        f"Matching complete: {len(labeled_clusters)} clusters, "
        f"{resolved} resolved, {confirmed} confirmed"
    )

    if output_path:
        atomic_write_json(output_path, labeled_clusters)

    return labeled_clusters


def match_new_announcements(
    open_clusters: List[Dict[str, Any]],
    new_announcements: List[Dict[str, Any]],
    model: str = "claude-sonnet-4-6",
) -> List[Dict[str, Any]]:
    """Incremental matching: check open rumors against new announcements only.

    Used in weekly runs for resolution checking.
    """
    if not new_announcements or not open_clusters:
        return open_clusters

    logger.info(
        f"Checking {len(open_clusters)} open clusters against "
        f"{len(new_announcements)} new announcements"
    )

    return match_clusters(
        open_clusters, new_announcements, model=model, batch_size=100
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Match rumor clusters to announcements")
    parser.add_argument("--clusters", default="data/rumor_clusters.json")
    parser.add_argument("--ground-truth", default="data/ground_truth.json")
    parser.add_argument("--output", default="data/matched_dataset.json")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    args = parser.parse_args()

    from lib.logging_config import setup_logging
    setup_logging("INFO")

    clusters_data = load_json(args.clusters)
    gt_data = load_json(args.ground_truth)

    if not clusters_data:
        print(f"No clusters in {args.clusters}")
        sys.exit(1)
    if not gt_data:
        print(f"No ground truth in {args.ground_truth}")
        sys.exit(1)

    match_clusters(
        clusters_data, gt_data, model=args.model, output_path=args.output
    )
