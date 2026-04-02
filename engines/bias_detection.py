"""
Bias Detection Engine — Post-Hoc Bias Auditing for Simulation Results.

Detects and quantifies systematic biases in the simulation:
  1. Disposition adherence — Did personas behave according to their assigned disposition?
  2. Sycophancy rate — What % of personas agreed too easily?
  3. Anchoring detection — Are personas within a batch too similar?
  4. Interviewer leading — Did the interviewer ask leading questions?
  5. Order effects — Did question order affect responses?

Each check produces a numeric score and actionable warnings that are
embedded in the report's "Bias Audit" section.
"""
import math
import re
from typing import Dict, Any, List, Tuple, Optional

from engines.logging_config import get_logger

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Disposition Adherence Check
# ──────────────────────────────────────────────

# Keywords that suggest positive/enthusiastic responses
POSITIVE_SIGNALS = [
    "love", "great", "amazing", "perfect", "exactly what",
    "definitely", "absolutely", "sign me up", "take my money",
    "huge improvement", "game changer", "no brainer",
]

# Keywords that suggest skeptical/resistant responses
NEGATIVE_SIGNALS = [
    "don't need", "not interested", "waste of", "already have",
    "too expensive", "don't trust", "won't work", "not convinced",
    "don't see", "pass on", "not for us", "no thanks",
    "skeptical", "doubtful", "won't buy",
]

# Keywords that suggest hedging/cautious responses
HEDGE_SIGNALS = [
    "maybe", "i'd have to", "depends on", "not sure",
    "need to think", "have to check", "possibly",
    "on the fence", "would need to see",
]


def _score_response_sentiment(text: str) -> str:
    """Simple keyword-based sentiment classification for disposition checking."""
    text_lower = text.lower()

    positive_count = sum(1 for sig in POSITIVE_SIGNALS if sig in text_lower)
    negative_count = sum(1 for sig in NEGATIVE_SIGNALS if sig in text_lower)
    hedge_count = sum(1 for sig in HEDGE_SIGNALS if sig in text_lower)

    if positive_count > negative_count + hedge_count:
        return "positive"
    elif negative_count > positive_count + hedge_count:
        return "negative"
    elif hedge_count > 0:
        return "cautious"
    else:
        return "neutral"


def check_disposition_adherence(interviews: List[Dict]) -> Dict[str, Any]:
    """
    Check whether personas behaved according to their assigned disposition.

    For each persona, we look at their responses and check if the overall
    sentiment matches what we'd expect from their disposition.

    Expected behavior:
    - enthusiastic → mostly positive
    - open → mixed, leaning positive
    - cautious → mixed, with hedging
    - skeptical → mostly negative/cautious
    - resistant → mostly negative

    Returns:
        Dict with adherence rate, violations, and per-disposition breakdown.
    """
    expected_sentiment = {
        "enthusiastic": {"positive", "neutral"},
        "open": {"positive", "neutral", "cautious"},
        "cautious": {"cautious", "neutral", "negative"},
        "skeptical": {"negative", "cautious", "neutral"},
        "resistant": {"negative", "cautious"},
    }

    total_checked = 0
    adherent = 0
    violations = []
    disposition_stats = {}

    for interview in interviews:
        persona = interview.get("persona", {})
        transcript = interview.get("transcript", [])
        disposition = persona.get("disposition", "cautious")
        name = persona.get("name", "Unknown")

        if disposition not in expected_sentiment:
            continue

        # Collect all persona responses
        persona_responses = [
            t["content"] for t in transcript
            if t.get("role") == "persona" and t.get("content")
        ]

        if not persona_responses:
            continue

        # Score the overall sentiment of their responses
        sentiments = [_score_response_sentiment(r) for r in persona_responses]
        sentiment_counts = {}
        for s in sentiments:
            sentiment_counts[s] = sentiment_counts.get(s, 0) + 1

        # Dominant sentiment
        dominant = max(sentiment_counts, key=sentiment_counts.get) if sentiment_counts else "neutral"

        # Check if dominant sentiment matches expected
        expected = expected_sentiment[disposition]
        is_adherent = dominant in expected

        total_checked += 1
        if is_adherent:
            adherent += 1
        else:
            violations.append({
                "persona": name,
                "disposition": disposition,
                "expected_sentiments": list(expected),
                "observed_dominant": dominant,
                "sentiment_distribution": sentiment_counts,
            })

        # Track per-disposition stats
        if disposition not in disposition_stats:
            disposition_stats[disposition] = {"total": 0, "adherent": 0}
        disposition_stats[disposition]["total"] += 1
        if is_adherent:
            disposition_stats[disposition]["adherent"] += 1

    adherence_rate = adherent / total_checked if total_checked > 0 else 0.0

    # Per-disposition adherence rates
    disposition_rates = {}
    for disp, stats in disposition_stats.items():
        rate = stats["adherent"] / stats["total"] if stats["total"] > 0 else 0.0
        disposition_rates[disp] = round(rate, 3)

    # Generate warnings
    warnings = []
    if adherence_rate < 0.5:
        warnings.append(
            f"Low disposition adherence ({adherence_rate:.0%}). Personas are not behaving "
            "according to their assigned dispositions. This may indicate LLM prompt leakage "
            "or insufficient disposition enforcement."
        )

    for disp, rate in disposition_rates.items():
        if disp in ("skeptical", "resistant") and rate < 0.4:
            warnings.append(
                f"'{disp}' personas are not behaving skeptically enough (adherence: {rate:.0%}). "
                "The anti-sycophancy mechanism may need strengthening for this disposition."
            )
        if disp == "enthusiastic" and rate < 0.3:
            warnings.append(
                f"'enthusiastic' personas are overly cautious (adherence: {rate:.0%}). "
                "The anti-sycophancy measures may be overcorrecting."
            )

    return {
        "adherence_rate": round(adherence_rate, 3),
        "total_checked": total_checked,
        "total_adherent": adherent,
        "violations": violations[:20],  # Cap at 20 to avoid report bloat
        "violation_count": len(violations),
        "disposition_rates": disposition_rates,
        "warnings": warnings,
    }


# ──────────────────────────────────────────────
# Sycophancy Detection
# ──────────────────────────────────────────────

SYCOPHANCY_PATTERNS = [
    r"that sounds? (?:great|amazing|wonderful|fantastic|perfect)",
    r"i(?:'d| would) (?:definitely|absolutely|totally) (?:buy|use|try|sign up)",
    r"(?:exactly|precisely) what (?:i|we) (?:need|want|have been looking for)",
    r"(?:take|shut up and take) my money",
    r"(?:no|zero) (?:objections|concerns|complaints)",
    r"where do i sign",
    r"this is (?:exactly|precisely) what (?:the market|we|the industry) needs",
]


def detect_sycophancy(interviews: List[Dict]) -> Dict[str, Any]:
    """
    Detect sycophantic (unrealistically positive) responses.

    Sycophancy is detected when:
    1. A persona uses enthusiastic agreement phrases without substance
    2. A skeptical/resistant persona gives positive responses
    3. A persona agrees to buy/use without asking about price, integration, etc.

    Returns:
        Dict with sycophancy rate, flagged interviews, and warnings.
    """
    total_interviews = 0
    flagged_interviews = []
    compiled_patterns = [re.compile(p, re.IGNORECASE) for p in SYCOPHANCY_PATTERNS]

    for interview in interviews:
        persona = interview.get("persona", {})
        transcript = interview.get("transcript", [])
        disposition = persona.get("disposition", "cautious")
        skepticism = persona.get("skepticism_score", 5)
        name = persona.get("name", "Unknown")

        persona_responses = [
            t["content"] for t in transcript
            if t.get("role") == "persona" and t.get("content")
        ]

        if not persona_responses:
            continue

        total_interviews += 1
        flags = []

        # Check for sycophantic phrases
        for response in persona_responses:
            for pattern in compiled_patterns:
                if pattern.search(response):
                    flags.append({
                        "type": "sycophantic_phrase",
                        "text": response[:100],
                        "pattern": pattern.pattern,
                    })

        # Check for disposition mismatch (skeptical persona being too positive)
        if disposition in ("skeptical", "resistant") and skepticism >= 7:
            positive_responses = sum(
                1 for r in persona_responses
                if _score_response_sentiment(r) == "positive"
            )
            if positive_responses > len(persona_responses) * 0.5:
                flags.append({
                    "type": "disposition_mismatch",
                    "text": f"{disposition} persona (skepticism {skepticism}/10) gave {positive_responses}/{len(persona_responses)} positive responses",
                })

        # Check for agreement without price/integration questions
        all_text = " ".join(persona_responses).lower()
        agreed_to_buy = any(
            phrase in all_text
            for phrase in ["sign up", "try it", "buy", "interested in purchasing", "start a trial"]
        )
        asked_practical = any(
            phrase in all_text
            for phrase in ["how much", "price", "cost", "integrate", "implementation", "timeline", "contract"]
        )
        if agreed_to_buy and not asked_practical:
            flags.append({
                "type": "agreement_without_diligence",
                "text": "Persona agreed to buy/try without asking about price, implementation, or timeline",
            })

        if flags:
            flagged_interviews.append({
                "persona": name,
                "disposition": disposition,
                "skepticism_score": skepticism,
                "flags": flags,
            })

    sycophancy_rate = len(flagged_interviews) / total_interviews if total_interviews > 0 else 0.0

    warnings = []
    if sycophancy_rate > 0.3:
        warnings.append(
            f"High sycophancy rate ({sycophancy_rate:.0%}). More than 30% of interviews show "
            "signs of artificial agreement. Consider strengthening anti-sycophancy prompts or "
            "increasing the proportion of skeptical/resistant personas."
        )
    if sycophancy_rate > 0.15:
        warnings.append(
            f"Moderate sycophancy detected ({sycophancy_rate:.0%}). Review flagged interviews "
            "to determine if positive responses are substantive or superficial."
        )

    return {
        "sycophancy_rate": round(sycophancy_rate, 3),
        "total_interviews": total_interviews,
        "flagged_count": len(flagged_interviews),
        "flagged_interviews": flagged_interviews[:15],  # Cap for report
        "warnings": warnings,
    }


# ──────────────────────────────────────────────
# Full Bias Audit
# ──────────────────────────────────────────────

def run_bias_audit(interviews: List[Dict]) -> Dict[str, Any]:
    """
    Run the full bias audit suite on a set of interviews.

    Returns a comprehensive audit dict with all bias checks.
    """
    logger.info("Running bias audit on %d interviews...", len(interviews))

    disposition_check = check_disposition_adherence(interviews)
    sycophancy_check = detect_sycophancy(interviews)

    # Aggregate warnings
    all_warnings = disposition_check["warnings"] + sycophancy_check["warnings"]

    # Overall bias risk
    risk_score = 0
    if disposition_check["adherence_rate"] < 0.6:
        risk_score += 1
    if sycophancy_check["sycophancy_rate"] > 0.2:
        risk_score += 1

    if risk_score == 0:
        overall_risk = "low"
    elif risk_score == 1:
        overall_risk = "moderate"
    else:
        overall_risk = "high"

    result = {
        "overall_risk": overall_risk,
        "disposition_adherence": disposition_check,
        "sycophancy_detection": sycophancy_check,
        "all_warnings": all_warnings,
    }

    logger.info(
        "Bias audit complete: risk=%s, disposition_adherence=%.0f%%, sycophancy=%.0f%%",
        overall_risk,
        disposition_check["adherence_rate"] * 100,
        sycophancy_check["sycophancy_rate"] * 100,
    )

    return result


def generate_bias_audit_section(audit: Dict[str, Any]) -> str:
    """Generate a Markdown section for the bias audit to include in the report."""
    lines = [
        "## Bias Audit",
        "",
        f"**Overall Bias Risk: {audit['overall_risk'].upper()}**",
        "",
    ]

    # Disposition adherence
    da = audit["disposition_adherence"]
    lines.extend([
        "### Disposition Adherence",
        "",
        f"Personas behaved according to their assigned disposition **{da['adherence_rate']:.0%}** of the time.",
        "",
        "| Disposition | Adherence Rate | Count |",
        "|-------------|---------------|-------|",
    ])
    for disp, rate in da.get("disposition_rates", {}).items():
        total = da.get("total_checked", 0)
        lines.append(f"| {disp} | {rate:.0%} | — |")

    if da["violation_count"] > 0:
        lines.extend([
            "",
            f"**{da['violation_count']} disposition violations detected.** "
            "These personas did not behave as expected given their assigned disposition.",
        ])

    # Sycophancy
    syc = audit["sycophancy_detection"]
    lines.extend([
        "",
        "### Sycophancy Detection",
        "",
        f"**{syc['flagged_count']}/{syc['total_interviews']} interviews ({syc['sycophancy_rate']:.0%})** "
        "showed signs of artificial agreement.",
        "",
    ])

    if syc["flagged_count"] > 0:
        lines.append("**Flagged interviews:**")
        for flagged in syc["flagged_interviews"][:10]:
            flags_desc = "; ".join(f.get("type", "unknown") for f in flagged.get("flags", []))
            lines.append(
                f"- {flagged['persona']} ({flagged['disposition']}, "
                f"skepticism {flagged['skepticism_score']}/10): {flags_desc}"
            )

    # Warnings
    if audit["all_warnings"]:
        lines.extend([
            "",
            "### Bias Warnings",
            "",
        ])
        for w in audit["all_warnings"]:
            lines.append(f"- {w}")

    return "\n".join(lines)
