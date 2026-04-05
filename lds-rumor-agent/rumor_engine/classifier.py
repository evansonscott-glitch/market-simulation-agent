#!/usr/bin/env python3
"""
Component 3a: Claude-Powered Rumor Classifier

Takes candidate Reddit posts and uses Claude to:
  1. Identify posts containing speculative claims
  2. Extract the specific claim
  3. Classify features (category, specificity, source type, etc.)

Output: data/classified_rumors.json
"""
import os
import sys
import hashlib
from datetime import date, datetime
from typing import List, Dict, Any, Optional

from lib.llm_client import chat_completion
from lib.json_parser import parse_llm_json
from lib.logging_config import get_logger

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from models import (
    RumorRecord, RumorFeatures, RumorResolution, SourcePlatform,
    AnnouncementCategory, Specificity, ClaimedSourceType,
    LanguageConfidence, Falsifiability, ResolutionStatus,
)
from scrapers.utils import atomic_write_json, load_json

logger = get_logger("rumor_engine.classifier")


def _load_prompt() -> str:
    """Load the classification prompt template."""
    prompt_path = os.path.join(
        os.path.dirname(__file__), "..", "config", "prompts", "classify.txt"
    )
    with open(prompt_path, "r") as f:
        return f.read()


def _format_batch(posts: List[Dict[str, Any]]) -> str:
    """Format a batch of posts for the Claude prompt."""
    lines = []
    for post in posts:
        text = post.get("body") or post.get("title") or ""
        title = post.get("title", "")
        sub = post.get("subreddit", "unknown")
        pid = post.get("id", "unknown")
        author = post.get("author", "unknown")
        post_date = ""
        if post.get("created_utc"):
            post_date = datetime.utcfromtimestamp(post["created_utc"]).strftime("%Y-%m-%d")

        lines.append(
            f"[POST_ID: {pid} | r/{sub} | u/{author} | {post_date}]\n"
            f"Title: {title}\n"
            f"Body: {text[:1000]}\n"
            f"---"
        )
    return "\n".join(lines)


def _generate_rumor_id(post_id: str, claim_index: int = 0) -> str:
    """Generate a deterministic rumor ID."""
    content = f"{post_id}:{claim_index}"
    hash_part = hashlib.md5(content.encode()).hexdigest()[:5]
    year = date.today().year
    return f"rum-{year}-{hash_part}"


def _safe_enum(enum_class, value: Optional[str], default):
    """Safely convert a string to an enum value."""
    if not value:
        return default
    try:
        return enum_class(value.lower().strip())
    except (ValueError, KeyError):
        return default


def classify_batch(
    posts: List[Dict[str, Any]],
    model: str = "claude-sonnet-4-6",
) -> List[RumorRecord]:
    """Send a batch of posts to Claude for classification."""
    prompt_template = _load_prompt()
    batch_text = _format_batch(posts)

    messages = [
        {"role": "system", "content": prompt_template},
        {"role": "user", "content": batch_text},
    ]

    response = chat_completion(
        messages=messages,
        model=model,
        temperature=0.3,
        max_tokens=8192,
    )

    parsed = parse_llm_json(response, expected_type=list, context="classify_batch")

    # Build a lookup for original post data
    post_lookup = {str(p.get("id", "")): p for p in posts}

    records = []
    for item in parsed:
        if not item.get("has_claim"):
            continue

        post_id = str(item.get("post_id", ""))
        original = post_lookup.get(post_id, {})

        # Parse date
        created_utc = original.get("created_utc", 0)
        if created_utc:
            post_date = datetime.utcfromtimestamp(created_utc).date()
        else:
            post_date = date.today()

        # Build features
        features = RumorFeatures(
            category=_safe_enum(AnnouncementCategory, item.get("category"), AnnouncementCategory.OTHER),
            specificity=_safe_enum(Specificity, item.get("specificity"), Specificity.VAGUE),
            claimed_source_type=_safe_enum(ClaimedSourceType, item.get("claimed_source_type"), ClaimedSourceType.SPECULATION),
            language_confidence=_safe_enum(LanguageConfidence, item.get("language_confidence"), LanguageConfidence.LOW),
            corroboration_count=0,
            falsifiability=_safe_enum(Falsifiability, item.get("falsifiability"), Falsifiability.LOW),
        )

        # Build source URL
        source_url = original.get("url", "")
        if source_url and not source_url.startswith("http"):
            source_url = f"https://reddit.com{source_url}"

        record = RumorRecord(
            id=_generate_rumor_id(post_id),
            source_platform=SourcePlatform.REDDIT,
            source_sub=f"r/{original.get('subreddit', 'unknown')}",
            source_url=source_url,
            author=f"u/{original.get('author', 'unknown')}",
            post_date=post_date,
            raw_text=(original.get("body") or original.get("title") or "")[:2000],
            extracted_claim=item.get("extracted_claim", ""),
            features=features,
        )
        records.append(record)

    logger.info(f"Classified batch: {len(posts)} posts -> {len(records)} rumors")
    return records


def classify_candidates(
    candidates: List[Dict[str, Any]],
    model: str = "claude-sonnet-4-6",
    batch_size: int = 50,
    output_path: Optional[str] = None,
) -> List[RumorRecord]:
    """Classify all candidates in batches."""
    all_records = []

    for i in range(0, len(candidates), batch_size):
        batch = candidates[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(candidates) + batch_size - 1) // batch_size
        logger.info(f"Classifying batch {batch_num}/{total_batches} ({len(batch)} posts)")

        try:
            records = classify_batch(batch, model)
            all_records.extend(records)
        except Exception as e:
            logger.error(f"Batch {batch_num} failed: {e}")
            continue

    logger.info(f"Classification complete: {len(all_records)} rumors from {len(candidates)} candidates")

    if output_path:
        atomic_write_json(output_path, [r.model_dump(mode="json") for r in all_records])

    return all_records


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Classify Reddit candidates into rumors")
    parser.add_argument("--input", default="data/reddit_candidates.json")
    parser.add_argument("--output", default="data/classified_rumors.json")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()

    from lib.logging_config import setup_logging
    setup_logging("INFO")

    candidates = load_json(args.input)
    if not candidates:
        print(f"No candidates found in {args.input}")
        sys.exit(1)

    classify_candidates(
        candidates, model=args.model, batch_size=args.batch_size,
        output_path=args.output,
    )
