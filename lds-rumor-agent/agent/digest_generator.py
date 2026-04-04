#!/usr/bin/env python3
"""
Component 5g-h: Digest Generator & Email Delivery

Generates the weekly HTML digest via Claude and sends it via Gmail SMTP.
"""
import os
import sys
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date, datetime
from typing import List, Dict, Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from engines.llm_client import chat_completion
from engines.json_parser import parse_llm_json
from engines.logging_config import get_logger

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from models import DigestRecord, ScoredRumor, ResolvedRumor, ModelStats, ConfidenceTier
from scrapers.utils import atomic_write_json, load_json

logger = get_logger("agent.digest")


def _load_digest_prompt() -> str:
    """Load the digest generation prompt."""
    prompt_path = os.path.join(
        os.path.dirname(__file__), "..", "config", "prompts", "digest.txt"
    )
    with open(prompt_path, "r") as f:
        return f.read()


def _format_digest_data(
    new_scored: List[Dict[str, Any]],
    resolved: List[Dict[str, Any]],
    still_watching: List[Dict[str, Any]],
    model_stats: Dict[str, Any],
) -> str:
    """Format all data for the digest prompt."""
    sections = []

    # New this week
    sections.append("== NEW RUMORS THIS WEEK ==")
    for r in new_scored[:20]:
        sections.append(
            f"Score: {r.get('score', 0):.2f} [{r.get('confidence_tier', 'noise')}]\n"
            f"Summary: {r.get('cluster_summary', '')}\n"
            f"Explanation: {r.get('score_explanation', '')}\n"
            f"Sources: {r.get('independent_source_count', 0)} independent\n"
            f"Post count: {len(r.get('rumor_ids', []))}\n"
            f"Earliest: {r.get('earliest_post_date', '')}\n"
        )

    # Resolved
    sections.append("\n== RESOLVED THIS WEEK ==")
    if resolved:
        for r in resolved:
            res = r.get("resolution", {})
            sections.append(
                f"Cluster: {r.get('cluster_summary', '')}\n"
                f"Original score: {r.get('score', 'N/A')}\n"
                f"Resolution: {res.get('status', 'unknown')}\n"
                f"Match quality: {res.get('match_quality', 'N/A')}\n"
                f"Days before announcement: {res.get('days_before_announcement', 'N/A')}\n"
            )
    else:
        sections.append("None this week.")

    # Still watching
    sections.append("\n== STILL WATCHING (top open rumors) ==")
    for r in still_watching[:10]:
        sections.append(
            f"Score: {r.get('score', 0):.2f} [{r.get('confidence_tier', 'noise')}] "
            f"— {r.get('cluster_summary', '')}"
        )

    # Model stats
    sections.append(f"\n== MODEL STATS ==")
    sections.append(json.dumps(model_stats, indent=2, default=str))

    return "\n".join(sections)


def generate_digest_html(
    new_scored: List[Dict[str, Any]],
    resolved: List[Dict[str, Any]],
    still_watching: List[Dict[str, Any]],
    model_stats: Dict[str, Any],
    model: str = "claude-sonnet-4-6",
) -> str:
    """Generate HTML digest using Claude."""
    prompt_template = _load_digest_prompt()
    data_text = _format_digest_data(new_scored, resolved, still_watching, model_stats)

    messages = [
        {"role": "system", "content": prompt_template},
        {"role": "user", "content": data_text},
    ]

    html = chat_completion(
        messages=messages,
        model=model,
        temperature=0.5,
        max_tokens=8192,
    )

    # If Claude returned the HTML in a code block, extract it
    if "```html" in html:
        start = html.index("```html") + 7
        end = html.index("```", start)
        html = html[start:end].strip()
    elif "```" in html:
        start = html.index("```") + 3
        end = html.index("```", start)
        html = html[start:end].strip()

    return html


def send_digest_email(
    html_content: str,
    sender_address: str,
    app_password: str,
    recipient: str,
    subject: Optional[str] = None,
    smtp_server: str = "smtp.gmail.com",
    smtp_port: int = 587,
) -> bool:
    """Send the HTML digest via Gmail SMTP."""
    today = date.today()
    week_num = today.isocalendar()[1]
    default_subject = f"LDS Rumor Digest — Week {week_num}, {today.year}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject or default_subject
    msg["From"] = sender_address
    msg["To"] = recipient

    # Plain text fallback
    plain = (
        f"LDS Rumor Intelligence Digest — Week {week_num}\n\n"
        "This email is best viewed in HTML format.\n"
        "If you're seeing this, check your email client's HTML settings."
    )

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(sender_address, app_password)
            server.send_message(msg)

        logger.info(f"Digest email sent to {recipient}")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Gmail SMTP auth failed. Check sender_address and app_password. "
            "Make sure you're using a Gmail App Password, not your regular password."
        )
        return False
    except Exception as e:
        logger.error(f"Failed to send digest email: {e}")
        return False


def build_digest_record(
    new_scored: List[Dict[str, Any]],
    resolved: List[Dict[str, Any]],
    model_stats: Dict[str, Any],
    week_start: date,
    week_end: date,
) -> DigestRecord:
    """Build a DigestRecord for archiving."""
    today = date.today()
    week_num = today.isocalendar()[1]

    new_rumors = []
    for r in new_scored:
        new_rumors.append(ScoredRumor(
            rumor_id=r.get("cluster_id", ""),
            cluster_summary=r.get("cluster_summary", ""),
            score=r.get("score", 0),
            confidence_tier=ConfidenceTier(r.get("confidence_tier", "noise")),
            score_explanation=r.get("score_explanation", ""),
            sources=[],
            post_count=len(r.get("rumor_ids", [])),
        ))

    resolved_rumors = []
    for r in resolved:
        res = r.get("resolution", {})
        resolved_rumors.append(ResolvedRumor(
            rumor_id=r.get("cluster_id", ""),
            original_score=r.get("score", 0),
            resolution=res.get("status", "unresolved"),
            prior_update_applied=True,
        ))

    return DigestRecord(
        digest_id=f"digest-{today.year}-W{week_num:02d}",
        week_start=week_start,
        week_end=week_end,
        new_rumors=new_rumors,
        resolved_rumors=resolved_rumors,
        model_stats=ModelStats(**model_stats) if model_stats else ModelStats(),
    )


def generate_and_send_digest(
    new_scored: List[Dict[str, Any]],
    resolved: List[Dict[str, Any]],
    still_watching: List[Dict[str, Any]],
    model_stats: Dict[str, Any],
    email_config: Dict[str, Any],
    model: str = "claude-sonnet-4-6",
    archive_dir: Optional[str] = None,
) -> bool:
    """Full digest pipeline: generate HTML, send email, archive."""
    logger.info("Generating weekly digest")

    # Generate HTML
    html = generate_digest_html(
        new_scored, resolved, still_watching, model_stats, model
    )

    # Send email
    sent = send_digest_email(
        html_content=html,
        sender_address=email_config.get("sender_address", ""),
        app_password=email_config.get("app_password", ""),
        recipient=email_config.get("recipient", ""),
        smtp_server=email_config.get("smtp_server", "smtp.gmail.com"),
        smtp_port=email_config.get("smtp_port", 587),
    )

    # Archive
    if archive_dir:
        today = date.today()
        week_num = today.isocalendar()[1]
        from datetime import timedelta
        week_start = today - timedelta(days=today.weekday() + 1)  # Last Sunday
        week_end = today

        record = build_digest_record(
            new_scored, resolved, model_stats, week_start, week_end
        )
        archive_path = os.path.join(
            archive_dir, f"digest-{today.year}-W{week_num:02d}.json"
        )
        atomic_write_json(archive_path, record.model_dump(mode="json"))

        # Also save the HTML
        html_path = os.path.join(
            archive_dir, f"digest-{today.year}-W{week_num:02d}.html"
        )
        with open(html_path, "w") as f:
            f.write(html)

    return sent


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate and send digest")
    parser.add_argument("--test", action="store_true", help="Send a test digest")
    args = parser.parse_args()

    from engines.logging_config import setup_logging
    setup_logging("INFO")

    if args.test:
        # Send a simple test email
        sender = os.environ.get("GMAIL_ADDRESS", "")
        password = os.environ.get("GMAIL_APP_PASSWORD", "")
        recipient = os.environ.get("DIGEST_RECIPIENT", "")

        if not all([sender, password, recipient]):
            print("Set GMAIL_ADDRESS, GMAIL_APP_PASSWORD, and DIGEST_RECIPIENT env vars")
            sys.exit(1)

        html = "<h1>Test Digest</h1><p>If you see this, email delivery is working.</p>"
        sent = send_digest_email(html, sender, password, recipient, subject="LDS Rumor Agent — Test")
        print("Test email sent!" if sent else "Failed to send test email")
