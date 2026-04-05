#!/usr/bin/env python3
"""
Component 5e: Resolution Checker

Checks open (unresolved) rumors against new official announcements.
When a match is found:
  1. Marks the rumor as resolved
  2. Updates prior tables with the new data point
  3. Updates author track records
"""
import os
import sys
from datetime import date
from typing import List, Dict, Any, Optional, Tuple

from lib.logging_config import get_logger

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from rumor_engine.matcher import match_new_announcements
from scrapers.utils import atomic_write_json, load_json

logger = get_logger("rumor_engine.resolver")


def resolve_rumors(
    open_clusters: List[Dict[str, Any]],
    new_announcements: List[Dict[str, Any]],
    rumor_records: List[Dict[str, Any]],
    author_records: Dict[str, Any],
    model: str = "claude-sonnet-4-6",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Check open rumors against new announcements and resolve matches.

    Returns:
        (updated_clusters, newly_resolved, updated_author_records)
    """
    if not new_announcements or not open_clusters:
        return open_clusters, [], author_records

    # Get only unresolved clusters
    unresolved = [
        c for c in open_clusters
        if c.get("resolution", {}).get("status", "unresolved") == "unresolved"
    ]

    if not unresolved:
        logger.info("No unresolved clusters to check")
        return open_clusters, [], author_records

    logger.info(
        f"Checking {len(unresolved)} open clusters against "
        f"{len(new_announcements)} new announcements"
    )

    # Match against new announcements
    matched = match_new_announcements(unresolved, new_announcements, model)

    # Identify newly resolved
    newly_resolved = []
    resolved_ids = set()

    for cluster in matched:
        res = cluster.get("resolution", {})
        status = res.get("status", "unresolved")
        if status != "unresolved":
            newly_resolved.append(cluster)
            resolved_ids.add(cluster.get("cluster_id", ""))
            res["resolved_date"] = str(date.today())

    # Update author records based on resolutions
    rumor_lookup = {r.get("id", ""): r for r in rumor_records}
    for cluster in newly_resolved:
        is_true = cluster.get("resolution", {}).get("status") in (
            "confirmed", "partially_confirmed"
        )
        for rid in cluster.get("rumor_ids", []):
            rumor = rumor_lookup.get(rid, {})
            author = rumor.get("author", "")
            if not author:
                continue

            if author not in author_records:
                author_records[author] = {
                    "author_id": author,
                    "platform": "reddit",
                    "correct_predictions": 0,
                    "wrong_predictions": 0,
                    "total_predictions": 0,
                    "first_seen": str(date.today()),
                    "last_seen": str(date.today()),
                }

            ar = author_records[author]
            ar["total_predictions"] = ar.get("total_predictions", 0) + 1
            ar["last_seen"] = str(date.today())
            if is_true:
                ar["correct_predictions"] = ar.get("correct_predictions", 0) + 1
            else:
                ar["wrong_predictions"] = ar.get("wrong_predictions", 0) + 1

    # Merge back into full cluster list
    matched_lookup = {c.get("cluster_id", ""): c for c in matched}
    updated = []
    for cluster in open_clusters:
        cid = cluster.get("cluster_id", "")
        if cid in matched_lookup:
            updated.append(matched_lookup[cid])
        else:
            updated.append(cluster)

    logger.info(f"Resolved {len(newly_resolved)} clusters this run")
    return updated, newly_resolved, author_records


def check_stale_rumors(
    open_clusters: List[Dict[str, Any]],
    stale_days: int = 180,
) -> List[Dict[str, Any]]:
    """Mark very old unresolved rumors as denied (stale timeout)."""
    today = date.today()
    stale_count = 0

    for cluster in open_clusters:
        res = cluster.get("resolution", {})
        if res.get("status", "unresolved") != "unresolved":
            continue

        earliest = cluster.get("earliest_post_date", "")
        if not earliest:
            continue

        try:
            if isinstance(earliest, str):
                from datetime import datetime
                earliest_date = datetime.strptime(earliest, "%Y-%m-%d").date()
            else:
                earliest_date = earliest
        except (ValueError, TypeError):
            continue

        days_old = (today - earliest_date).days
        if days_old >= stale_days:
            res["status"] = "denied"
            res["resolved_date"] = str(today)
            res["match_quality"] = "no_match"
            cluster["resolution"] = res
            stale_count += 1

    if stale_count:
        logger.info(f"Marked {stale_count} clusters as denied (stale, >{stale_days} days)")

    return open_clusters
