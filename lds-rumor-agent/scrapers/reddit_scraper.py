#!/usr/bin/env python3
"""
Component 2: Reddit Rumor Scraper

Two modes:
  1. Historical backfill via Arctic Shift API (12 months, for training)
  2. Live weekly scrape via PRAW (last 7 days, for production)

Applies keyword filtering to reduce volume before sending to Claude.
Output: data/reddit_raw.json + data/reddit_candidates.json
"""
import os
import sys
import re
import json
import time
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any, Set

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from engines.logging_config import get_logger

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from models import SourcePlatform
from scrapers.utils import fetch_html, rate_limit_sleep, atomic_write_json, load_json

logger = get_logger("scrapers.reddit")

# Default speculative keywords
DEFAULT_KEYWORDS = [
    "i heard", "rumor", "prediction", "my bishop said",
    "my stake president", "someone at cob", "i bet they",
    "wouldn't be surprised", "anyone else hearing", "temple in",
    "going to announce", "new temple", "called as",
    "handbook change", "policy change", "i think they'll",
    "speculation", "inside source", "confirmed", "unconfirmed", "leaked",
    "my source", "word is", "apparently", "reportedly",
]

DEFAULT_SUBREDDITS = [
    "latterdaysaints", "lds", "mormon", "exmormon", "temples",
]

# Church-related keywords for engagement filter
CHURCH_KEYWORDS = [
    "church", "temple", "prophet", "apostle", "general conference",
    "lds", "latter-day", "missionary", "stake", "ward", "bishop",
    "handbook", "byu", "relief society", "priesthood", "deseret",
    "ensign peak", "newsroom", "first presidency",
]


# ──────────────────────────────────────────────
# Arctic Shift API (Historical Backfill)
# ──────────────────────────────────────────────

ARCTIC_SHIFT_BASE = "https://arctic-shift.photon-reddit.com/api/posts/search"
ARCTIC_SHIFT_COMMENTS = "https://arctic-shift.photon-reddit.com/api/comments/search"


def _arctic_shift_search(
    endpoint: str,
    subreddit: str,
    after: datetime,
    before: datetime,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Query Arctic Shift API for posts or comments."""
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
    import json as json_mod

    params = {
        "subreddit": subreddit,
        "after": int(after.timestamp()),
        "before": int(before.timestamp()),
        "limit": limit,
        "sort": "desc",
        "sort_type": "created_utc",
    }

    url = f"{endpoint}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "lds-rumor-agent/1.0"})

    try:
        with urlopen(req, timeout=30) as resp:
            data = json_mod.loads(resp.read().decode("utf-8"))
            return data.get("data", [])
    except Exception as e:
        logger.warning(f"Arctic Shift query failed for r/{subreddit}: {e}")
        return []


def scrape_historical_reddit(
    subreddits: Optional[List[str]] = None,
    lookback_months: int = 12,
    output_raw_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Scrape historical Reddit posts via Arctic Shift API."""
    subs = subreddits or DEFAULT_SUBREDDITS
    cutoff = datetime.utcnow() - timedelta(days=lookback_months * 30)
    now = datetime.utcnow()
    all_posts = []

    for sub in subs:
        logger.info(f"Scraping historical r/{sub} ({lookback_months} months)")
        # Paginate by month chunks to stay within API limits
        chunk_start = cutoff
        while chunk_start < now:
            chunk_end = min(chunk_start + timedelta(days=30), now)

            # Fetch posts
            posts = _arctic_shift_search(
                ARCTIC_SHIFT_BASE, sub, chunk_start, chunk_end, limit=100
            )
            for post in posts:
                all_posts.append(_normalize_reddit_post(post, sub, "post"))

            # Fetch comments
            comments = _arctic_shift_search(
                ARCTIC_SHIFT_COMMENTS, sub, chunk_start, chunk_end, limit=100
            )
            for comment in comments:
                all_posts.append(_normalize_reddit_post(comment, sub, "comment"))

            logger.info(
                f"  r/{sub} {chunk_start.date()} - {chunk_end.date()}: "
                f"{len(posts)} posts, {len(comments)} comments"
            )
            chunk_start = chunk_end
            rate_limit_sleep(0.5, 1.5)

    logger.info(f"Historical scrape: {len(all_posts)} total items")

    if output_raw_path:
        atomic_write_json(output_raw_path, all_posts)

    return all_posts


# ──────────────────────────────────────────────
# PRAW Live Scraping (Weekly)
# ──────────────────────────────────────────────

def scrape_weekly_reddit(
    client_id: str,
    client_secret: str,
    user_agent: str = "lds-rumor-agent/1.0",
    subreddits: Optional[List[str]] = None,
    days_back: int = 7,
    output_raw_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Scrape last N days of Reddit via PRAW."""
    try:
        import praw
    except ImportError:
        logger.error("PRAW not installed. Run: pip install praw")
        return []

    subs = subreddits or DEFAULT_SUBREDDITS
    cutoff = datetime.utcnow() - timedelta(days=days_back)
    all_posts = []

    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )

    for sub_name in subs:
        logger.info(f"Scraping live r/{sub_name} (last {days_back} days)")
        try:
            subreddit = reddit.subreddit(sub_name)

            # Get new posts
            for submission in subreddit.new(limit=500):
                post_time = datetime.utcfromtimestamp(submission.created_utc)
                if post_time < cutoff:
                    break

                post_data = {
                    "id": submission.id,
                    "type": "post",
                    "subreddit": sub_name,
                    "author": str(submission.author) if submission.author else "[deleted]",
                    "created_utc": submission.created_utc,
                    "title": submission.title,
                    "body": submission.selftext,
                    "score": submission.score,
                    "num_comments": submission.num_comments,
                    "url": f"https://reddit.com{submission.permalink}",
                }
                all_posts.append(post_data)

                # Get comments if engagement is high enough
                if submission.num_comments >= 5:
                    submission.comments.replace_more(limit=0)
                    for comment in submission.comments.list():
                        comment_time = datetime.utcfromtimestamp(comment.created_utc)
                        if comment_time < cutoff:
                            continue
                        comment_data = {
                            "id": comment.id,
                            "type": "comment",
                            "subreddit": sub_name,
                            "author": str(comment.author) if comment.author else "[deleted]",
                            "created_utc": comment.created_utc,
                            "title": "",
                            "body": comment.body,
                            "score": comment.score,
                            "num_comments": 0,
                            "url": f"https://reddit.com{comment.permalink}",
                            "parent_id": comment.parent_id,
                        }
                        all_posts.append(comment_data)

        except Exception as e:
            logger.error(f"Error scraping r/{sub_name}: {e}")
            continue

    logger.info(f"Live scrape: {len(all_posts)} total items")

    if output_raw_path:
        atomic_write_json(output_raw_path, all_posts)

    return all_posts


# ──────────────────────────────────────────────
# Normalization
# ──────────────────────────────────────────────

def _normalize_reddit_post(raw: Dict, subreddit: str, post_type: str) -> Dict[str, Any]:
    """Normalize Arctic Shift post/comment to our standard format."""
    created = raw.get("created_utc", 0)
    if isinstance(created, str):
        created = int(float(created))

    return {
        "id": raw.get("id", ""),
        "type": post_type,
        "subreddit": subreddit,
        "author": raw.get("author", "[deleted]"),
        "created_utc": created,
        "title": raw.get("title", ""),
        "body": raw.get("selftext", "") or raw.get("body", ""),
        "score": raw.get("score", 0),
        "num_comments": raw.get("num_comments", 0),
        "url": raw.get("permalink", ""),
    }


# ──────────────────────────────────────────────
# Keyword Filtering
# ──────────────────────────────────────────────

def filter_candidates(
    posts: List[Dict[str, Any]],
    keywords: Optional[List[str]] = None,
    min_engagement: int = 10,
    output_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter posts to speculative candidates using keyword + engagement heuristics."""
    kw_list = [k.lower() for k in (keywords or DEFAULT_KEYWORDS)]
    candidates = []
    seen_ids: Set[str] = set()

    for post in posts:
        pid = post.get("id", "")
        if pid in seen_ids:
            continue

        text = f"{post.get('title', '')} {post.get('body', '')}".lower()

        # Check speculative keywords
        has_keyword = any(kw in text for kw in kw_list)

        # Check high engagement with Church content
        has_engagement = (
            post.get("num_comments", 0) >= min_engagement
            and any(ck in text for ck in CHURCH_KEYWORDS)
        )

        if has_keyword or has_engagement:
            candidates.append(post)
            seen_ids.add(pid)

    logger.info(f"Filtered {len(posts)} posts -> {len(candidates)} candidates")

    if output_path:
        atomic_write_json(output_path, candidates)

    return candidates


# ──────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────

def scrape_reddit(
    mode: str = "historical",
    client_id: str = "",
    client_secret: str = "",
    user_agent: str = "lds-rumor-agent/1.0",
    subreddits: Optional[List[str]] = None,
    lookback_months: int = 12,
    days_back: int = 7,
    keywords: Optional[List[str]] = None,
    min_engagement: int = 10,
    output_raw: Optional[str] = None,
    output_candidates: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Full Reddit scraping pipeline."""
    if mode == "historical":
        raw = scrape_historical_reddit(subreddits, lookback_months, output_raw)
    elif mode == "live":
        raw = scrape_weekly_reddit(
            client_id, client_secret, user_agent, subreddits, days_back, output_raw
        )
    else:
        raise ValueError(f"Unknown mode: {mode}. Use 'historical' or 'live'.")

    candidates = filter_candidates(raw, keywords, min_engagement, output_candidates)
    return candidates


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scrape Reddit for LDS rumors")
    parser.add_argument("--mode", choices=["historical", "live"], default="historical")
    parser.add_argument("--lookback", type=int, default=12, help="Months for historical")
    parser.add_argument("--days", type=int, default=7, help="Days for live mode")
    parser.add_argument("--output-raw", default="data/reddit_raw.json")
    parser.add_argument("--output-candidates", default="data/reddit_candidates.json")
    args = parser.parse_args()

    from engines.logging_config import setup_logging
    setup_logging("INFO")

    if args.mode == "live":
        # Load credentials from env
        cid = os.environ.get("REDDIT_CLIENT_ID", "")
        csecret = os.environ.get("REDDIT_CLIENT_SECRET", "")
        ua = os.environ.get("REDDIT_USER_AGENT", "lds-rumor-agent/1.0")
        if not cid or not csecret:
            print("Error: Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET env vars")
            sys.exit(1)
        scrape_reddit(
            mode="live", client_id=cid, client_secret=csecret, user_agent=ua,
            days_back=args.days, output_raw=args.output_raw,
            output_candidates=args.output_candidates,
        )
    else:
        scrape_reddit(
            mode="historical", lookback_months=args.lookback,
            output_raw=args.output_raw, output_candidates=args.output_candidates,
        )
