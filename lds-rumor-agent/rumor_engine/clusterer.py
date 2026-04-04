#!/usr/bin/env python3
"""
Component 3b: Claude-Powered Corroboration Clusterer

Groups classified rumors into clusters where multiple posts make essentially
the same prediction. Counts independent sources per cluster.

Output: data/rumor_clusters.json
"""
import os
import sys
from datetime import date, datetime
from typing import List, Dict, Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from engines.llm_client import chat_completion
from engines.json_parser import parse_llm_json
from engines.logging_config import get_logger

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from models import RumorRecord, RumorCluster, RumorResolution
from scrapers.utils import atomic_write_json, load_json

logger = get_logger("rumor_engine.clusterer")


def _load_prompt() -> str:
    """Load the clustering prompt template."""
    prompt_path = os.path.join(
        os.path.dirname(__file__), "..", "config", "prompts", "cluster.txt"
    )
    with open(prompt_path, "r") as f:
        return f.read()


def _format_rumors_for_clustering(rumors: List[Dict[str, Any]]) -> str:
    """Format classified rumors for the clustering prompt."""
    lines = []
    for r in rumors:
        rid = r.get("id", "unknown")
        claim = r.get("extracted_claim", "")
        author = r.get("author", "unknown")
        post_date = r.get("post_date", "")
        sub = r.get("source_sub", "")
        category = ""
        if isinstance(r.get("features"), dict):
            category = r["features"].get("category", "")

        lines.append(
            f"[{rid}] ({sub}, {author}, {post_date}) [{category}]: {claim}"
        )
    return "\n".join(lines)


def cluster_batch(
    rumors: List[Dict[str, Any]],
    model: str = "claude-sonnet-4-6",
) -> List[RumorCluster]:
    """Send a batch of rumors to Claude for clustering."""
    prompt_template = _load_prompt()
    rumors_text = _format_rumors_for_clustering(rumors)

    messages = [
        {"role": "system", "content": prompt_template},
        {"role": "user", "content": rumors_text},
    ]

    response = chat_completion(
        messages=messages,
        model=model,
        temperature=0.2,
        max_tokens=8192,
    )

    parsed = parse_llm_json(response, expected_type=list, context="cluster_batch")

    clusters = []
    for item in parsed:
        try:
            earliest = item.get("earliest_post_date", str(date.today()))
            if isinstance(earliest, str):
                try:
                    earliest = datetime.strptime(earliest, "%Y-%m-%d").date()
                except ValueError:
                    earliest = date.today()

            cluster = RumorCluster(
                cluster_id=item.get("cluster_id", ""),
                cluster_summary=item.get("cluster_summary", ""),
                rumor_ids=item.get("rumor_ids", []),
                independent_source_count=max(1, item.get("independent_source_count", 1)),
                earliest_post_date=earliest,
            )
            clusters.append(cluster)
        except Exception as e:
            logger.warning(f"Failed to parse cluster: {e}")
            continue

    logger.info(f"Clustered {len(rumors)} rumors into {len(clusters)} clusters")
    return clusters


def cluster_rumors(
    rumors: List[Dict[str, Any]],
    model: str = "claude-sonnet-4-6",
    batch_size: int = 200,
    output_path: Optional[str] = None,
) -> List[RumorCluster]:
    """Cluster all classified rumors, with batching for large volumes.

    For large datasets, processes in overlapping windows and merges
    clusters that appear across batch boundaries.
    """
    if len(rumors) <= batch_size:
        clusters = cluster_batch(rumors, model)
    else:
        # Process in overlapping windows
        all_clusters = []
        overlap = batch_size // 4  # 25% overlap

        for i in range(0, len(rumors), batch_size - overlap):
            batch = rumors[i:i + batch_size]
            batch_num = i // (batch_size - overlap) + 1
            logger.info(f"Clustering batch {batch_num} ({len(batch)} rumors)")

            try:
                batch_clusters = cluster_batch(batch, model)
                all_clusters.extend(batch_clusters)
            except Exception as e:
                logger.error(f"Clustering batch {batch_num} failed: {e}")
                continue

        # Merge clusters that share rumor IDs across batches
        clusters = _merge_overlapping_clusters(all_clusters)

    if output_path:
        atomic_write_json(output_path, [c.model_dump(mode="json") for c in clusters])

    logger.info(f"Final cluster count: {len(clusters)}")
    return clusters


def _merge_overlapping_clusters(clusters: List[RumorCluster]) -> List[RumorCluster]:
    """Merge clusters that share rumor IDs (from overlapping batch windows)."""
    # Build a union-find structure keyed by rumor_id
    parent: Dict[str, int] = {}  # rumor_id -> cluster_index
    merged: Dict[int, RumorCluster] = {}

    for idx, cluster in enumerate(clusters):
        # Check if any rumor in this cluster already belongs to an existing cluster
        existing_idx = None
        for rid in cluster.rumor_ids:
            if rid in parent:
                existing_idx = parent[rid]
                break

        if existing_idx is not None:
            # Merge into existing
            existing = merged[existing_idx]
            new_ids = set(existing.rumor_ids) | set(cluster.rumor_ids)
            existing.rumor_ids = list(new_ids)
            existing.independent_source_count = max(
                existing.independent_source_count, cluster.independent_source_count
            )
            existing.earliest_post_date = min(
                existing.earliest_post_date, cluster.earliest_post_date
            )
            # Update parent map
            for rid in cluster.rumor_ids:
                parent[rid] = existing_idx
        else:
            # New cluster
            merged[idx] = cluster
            for rid in cluster.rumor_ids:
                parent[rid] = idx

    result = list(merged.values())
    logger.info(f"Merged {len(clusters)} batch clusters -> {len(result)} unique clusters")
    return result


def update_clusters_with_new_rumors(
    existing_clusters: List[RumorCluster],
    new_rumors: List[Dict[str, Any]],
    model: str = "claude-sonnet-4-6",
) -> List[RumorCluster]:
    """Check if new rumors corroborate existing clusters.

    Used in weekly runs to increment corroboration counts.
    """
    if not new_rumors:
        return existing_clusters

    # Format existing clusters for Claude to match against
    cluster_summaries = "\n".join(
        f"[{c.cluster_id}]: {c.cluster_summary} (sources: {c.independent_source_count})"
        for c in existing_clusters
    )

    new_text = _format_rumors_for_clustering(new_rumors)

    prompt = (
        "You have existing rumor clusters and new rumors. For each new rumor, determine:\n"
        "1. Does it match an existing cluster? If so, which cluster_id?\n"
        "2. If not, should it start a new cluster?\n\n"
        "Respond with JSON array:\n"
        '{"rumor_id": "...", "matches_cluster": "cluster-NNNN" or null, "is_independent_source": true/false}\n\n'
        f"Existing clusters:\n{cluster_summaries}\n\n"
        f"New rumors:\n{new_text}"
    )

    messages = [
        {"role": "user", "content": prompt},
    ]

    response = chat_completion(messages=messages, model=model, temperature=0.2, max_tokens=4096)
    matches = parse_llm_json(response, expected_type=list, context="update_clusters")

    # Apply matches
    cluster_lookup = {c.cluster_id: c for c in existing_clusters}
    unmatched = []

    for match in matches:
        cluster_id = match.get("matches_cluster")
        rumor_id = match.get("rumor_id", "")

        if cluster_id and cluster_id in cluster_lookup:
            cluster = cluster_lookup[cluster_id]
            if rumor_id not in cluster.rumor_ids:
                cluster.rumor_ids.append(rumor_id)
            if match.get("is_independent_source"):
                cluster.independent_source_count += 1
        elif rumor_id:
            unmatched.append(rumor_id)

    # New unmatched rumors get clustered separately
    if unmatched:
        unmatched_data = [r for r in new_rumors if r.get("id") in set(unmatched)]
        if unmatched_data:
            new_clusters = cluster_batch(unmatched_data, model)
            existing_clusters.extend(new_clusters)

    return existing_clusters


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Cluster classified rumors")
    parser.add_argument("--input", default="data/classified_rumors.json")
    parser.add_argument("--output", default="data/rumor_clusters.json")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    args = parser.parse_args()

    from engines.logging_config import setup_logging
    setup_logging("INFO")

    rumors = load_json(args.input)
    if not rumors:
        print(f"No rumors found in {args.input}")
        sys.exit(1)

    cluster_rumors(rumors, model=args.model, output_path=args.output)
