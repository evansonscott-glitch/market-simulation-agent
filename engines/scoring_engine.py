"""
Scoring Engine — Objective, Code-Based Conversation Scoring

Replaces the subjective 1-5 rubric with deterministic, measurable KPIs
that can be calculated programmatically. This enables a true optimization
loop: run → score → revise → re-run → compare scores.

Scoring Dimensions:
  1. Objection Bypass Rate — % of objections where agent response led to positive next turn
  2. Attribute Contradiction Score — # of times persona contradicts their defined attributes
  3. Turns to Resolution — Turn count to terminal state
  4. Trust Signal Hit Rate — % of trust-related objections followed by a trust signal within 1 turn
  5. Cross-Sell Success Rate — % of cross-sell attempts that got a positive response
  6. Conversion Rate — % of conversations ending in success (per trigger)
  7. Sentiment Velocity — Change in sentiment from first half to second half

Each dimension produces a numeric score. The composite score is a weighted average.
"""
import json
import os
import re
from typing import Dict, Any, List, Optional, Tuple

from engines.logging_config import get_logger
from engines.llm_client import chat_completion, LLMRetryExhausted, LLMResponseEmpty
from engines.json_parser import parse_llm_json, JSONParseError

logger = get_logger(__name__)

# Default weights for the composite score
DEFAULT_WEIGHTS = {
    "objection_bypass_rate": 0.20,
    "attribute_consistency": 0.15,
    "turns_to_resolution": 0.10,
    "trust_signal_hit_rate": 0.15,
    "cross_sell_success_rate": 0.10,
    "conversion": 0.15,
    "sentiment_velocity": 0.15,
}


# ──────────────────────────────────────────────
# Turn-Level Analysis (LLM-based)
# ──────────────────────────────────────────────

def _analyze_turns(
    transcript: List[Dict[str, str]],
    persona: Dict[str, Any],
    model: str,
) -> Dict[str, Any]:
    """
    Use an LLM to classify each turn in the conversation.
    
    For each user (persona) turn, classifies:
    - sentiment: -1.0 to 1.0
    - contains_objection: bool
    - objection_type: str or null (price, trust, timing, need, competition, etc.)
    - contradicts_persona: bool
    - contradiction_detail: str or null
    
    For each agent turn, classifies:
    - contains_trust_signal: bool
    - contains_cross_sell: bool
    - response_quality: "positive", "neutral", "negative" (effect on user)
    
    Returns a dict with classified turns.
    """
    # Format the transcript
    transcript_text = ""
    for i, turn in enumerate(transcript):
        role = turn.get("role", "unknown")
        content = turn.get("content", "")
        transcript_text += f"Turn {i+1} [{role}]: {content}\n\n"
    
    # Format persona attributes
    persona_attrs = ""
    for key, val in persona.items():
        if key not in ("_raw", "interview_result") and not key.startswith("_"):
            persona_attrs += f"- {key}: {val}\n"
    
    system_prompt = f"""You are an objective conversation analyst scoring a simulated sales conversation.

## PERSONA ATTRIBUTES
{persona_attrs}

## YOUR JOB
Classify each turn in the conversation. Return a JSON object with a "turns" array.

For each turn, provide:
{{
  "turn_number": 1,
  "role": "user" or "agent",
  "sentiment": -1.0 to 1.0 (only for user turns, null for agent),
  "contains_objection": true/false (only for user turns),
  "objection_type": "price" | "trust" | "timing" | "need" | "competition" | "experience" | null,
  "contradicts_persona": true/false (only for user turns — does this turn contradict the persona's defined attributes?),
  "contradiction_detail": "string explaining the contradiction" or null,
  "contains_trust_signal": true/false (only for agent turns — does the agent mention local presence, years in business, family-owned, certifications, etc.?),
  "contains_cross_sell": true/false (only for agent turns — does the agent introduce a different service?),
  "user_reaction": "positive" | "neutral" | "negative" (only for user turns — overall tone/direction)
}}

## RULES
1. Be strict about contradictions — only flag if the persona DIRECTLY contradicts a defined attribute.
2. Sentiment should reflect the actual emotional tone, not just the words.
3. A trust signal is any mention of local presence, years in business, family ownership, certifications, warranties, BBB rating, etc.
4. A cross-sell is any introduction of a service different from the primary topic.

Return ONLY a JSON object: {{"turns": [...], "final_outcome": "success" | "decline" | "handoff" | "unclear"}}"""

    user_prompt = f"""Analyze this conversation:

{transcript_text}"""

    try:
        response = chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=model,
            temperature=0.1,
            max_tokens=4000,
        )
        
        analysis = parse_llm_json(response, expected_type=dict, context="turn analysis")
        return analysis
        
    except (JSONParseError, LLMRetryExhausted, LLMResponseEmpty) as e:
        logger.warning("Turn analysis failed: %s", str(e)[:200])
        return {"turns": [], "final_outcome": "unclear"}


# ──────────────────────────────────────────────
# Dimension Calculators
# ──────────────────────────────────────────────

def _calc_objection_bypass_rate(turns: List[Dict]) -> float:
    """
    Objection Bypass Rate: % of objections where the NEXT user turn
    has a "positive" or "neutral" reaction.
    
    Returns 0.0-1.0 (or -1.0 if no objections found).
    """
    objection_indices = []
    for i, turn in enumerate(turns):
        if turn.get("contains_objection") and turn.get("role") == "user":
            objection_indices.append(i)
    
    if not objection_indices:
        return -1.0  # No objections to measure
    
    bypassed = 0
    for obj_idx in objection_indices:
        # Find the next user turn after this objection
        for j in range(obj_idx + 1, len(turns)):
            if turns[j].get("role") == "user":
                reaction = turns[j].get("user_reaction", "neutral")
                if reaction in ("positive", "neutral"):
                    bypassed += 1
                break
    
    return bypassed / len(objection_indices)


def _calc_attribute_consistency(turns: List[Dict]) -> float:
    """
    Attribute Consistency Score: 1.0 minus (contradictions / user_turns).
    
    Returns 0.0-1.0 (higher = more consistent).
    """
    user_turns = [t for t in turns if t.get("role") == "user"]
    if not user_turns:
        return 1.0
    
    contradictions = sum(1 for t in user_turns if t.get("contradicts_persona"))
    return 1.0 - (contradictions / len(user_turns))


def _calc_turns_to_resolution(turns: List[Dict], final_outcome: str) -> float:
    """
    Turns to Resolution: Normalized score based on turn count.
    
    Scoring:
    - 1-4 turns: 1.0 (excellent)
    - 5-6 turns: 0.8
    - 7-8 turns: 0.6
    - 9-10 turns: 0.4
    - 11+ turns: 0.2
    - No resolution: 0.0
    
    Returns 0.0-1.0.
    """
    if final_outcome == "unclear":
        return 0.0
    
    n_turns = len(turns)
    
    if n_turns <= 4:
        return 1.0
    elif n_turns <= 6:
        return 0.8
    elif n_turns <= 8:
        return 0.6
    elif n_turns <= 10:
        return 0.4
    else:
        return 0.2


def _calc_trust_signal_hit_rate(turns: List[Dict]) -> float:
    """
    Trust Signal Hit Rate: % of trust-related objections where the agent
    deploys a trust signal within the next 1-2 agent turns.
    
    Returns 0.0-1.0 (or -1.0 if no trust objections found).
    """
    trust_objection_indices = []
    for i, turn in enumerate(turns):
        if (turn.get("contains_objection") and 
            turn.get("objection_type") == "trust" and
            turn.get("role") == "user"):
            trust_objection_indices.append(i)
    
    if not trust_objection_indices:
        return -1.0  # No trust objections to measure
    
    hits = 0
    for obj_idx in trust_objection_indices:
        # Check the next 2 agent turns for a trust signal
        agent_turns_checked = 0
        for j in range(obj_idx + 1, len(turns)):
            if turns[j].get("role") == "agent":
                agent_turns_checked += 1
                if turns[j].get("contains_trust_signal"):
                    hits += 1
                    break
                if agent_turns_checked >= 2:
                    break
    
    return hits / len(trust_objection_indices)


def _calc_cross_sell_success_rate(turns: List[Dict]) -> float:
    """
    Cross-Sell Success Rate: % of cross-sell attempts that got a
    positive reaction in the next user turn.
    
    Returns 0.0-1.0 (or -1.0 if no cross-sell attempts).
    """
    cross_sell_indices = []
    for i, turn in enumerate(turns):
        if turn.get("contains_cross_sell") and turn.get("role") == "agent":
            cross_sell_indices.append(i)
    
    if not cross_sell_indices:
        return -1.0  # No cross-sell attempts
    
    successes = 0
    for cs_idx in cross_sell_indices:
        # Find the next user turn
        for j in range(cs_idx + 1, len(turns)):
            if turns[j].get("role") == "user":
                reaction = turns[j].get("user_reaction", "neutral")
                if reaction == "positive":
                    successes += 1
                break
    
    return successes / len(cross_sell_indices)


def _calc_conversion(final_outcome: str) -> float:
    """
    Conversion: Binary — did the conversation end in success?
    
    Returns 1.0 (success) or 0.0 (anything else).
    """
    return 1.0 if final_outcome == "success" else 0.0


def _calc_sentiment_velocity(turns: List[Dict]) -> float:
    """
    Sentiment Velocity: Change in average sentiment from first half
    to second half of the conversation.
    
    A positive velocity means the conversation improved over time.
    Normalized to 0.0-1.0 scale (0.5 = no change, 1.0 = max improvement).
    
    Returns 0.0-1.0.
    """
    user_turns = [t for t in turns if t.get("role") == "user" and t.get("sentiment") is not None]
    
    if len(user_turns) < 2:
        return 0.5  # Not enough data
    
    mid = len(user_turns) // 2
    first_half = user_turns[:mid]
    second_half = user_turns[mid:]
    
    avg_first = sum(t.get("sentiment", 0) for t in first_half) / len(first_half)
    avg_second = sum(t.get("sentiment", 0) for t in second_half) / len(second_half)
    
    # Velocity: change from first to second half
    # Range: -2.0 to +2.0 → normalize to 0.0-1.0
    velocity = avg_second - avg_first
    normalized = (velocity + 2.0) / 4.0  # Maps [-2, 2] → [0, 1]
    
    return max(0.0, min(1.0, normalized))


# ──────────────────────────────────────────────
# Composite Scorer
# ──────────────────────────────────────────────

def score_conversation(
    transcript: List[Dict[str, str]],
    persona: Dict[str, Any],
    model: str,
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Score a single conversation across all 7 dimensions.
    
    Args:
        transcript: List of turn dicts with 'role' and 'content'.
        persona: The persona dict (for attribute checking).
        model: LLM model to use for turn analysis.
        weights: Optional custom weights for composite score.
    
    Returns:
        A dict with individual dimension scores and composite score.
    """
    weights = weights or DEFAULT_WEIGHTS
    
    # Step 1: Analyze turns using LLM
    analysis = _analyze_turns(transcript, persona, model)
    turns = analysis.get("turns", [])
    final_outcome = analysis.get("final_outcome", "unclear")
    
    if not turns:
        logger.warning("No turns returned from analysis — returning zero scores")
        return {
            "dimensions": {k: 0.0 for k in weights},
            "composite_score": 0.0,
            "final_outcome": final_outcome,
            "turn_count": len(transcript),
            "analysis_failed": True,
        }
    
    # Step 2: Calculate each dimension
    scores = {
        "objection_bypass_rate": _calc_objection_bypass_rate(turns),
        "attribute_consistency": _calc_attribute_consistency(turns),
        "turns_to_resolution": _calc_turns_to_resolution(turns, final_outcome),
        "trust_signal_hit_rate": _calc_trust_signal_hit_rate(turns),
        "cross_sell_success_rate": _calc_cross_sell_success_rate(turns),
        "conversion": _calc_conversion(final_outcome),
        "sentiment_velocity": _calc_sentiment_velocity(turns),
    }
    
    # Step 3: Calculate composite score
    # For dimensions with -1.0 (not applicable), exclude from composite
    active_weights = {}
    active_scores = {}
    for dim, score in scores.items():
        if score >= 0:
            active_weights[dim] = weights.get(dim, 0.0)
            active_scores[dim] = score
    
    # Normalize active weights to sum to 1.0
    total_active_weight = sum(active_weights.values())
    if total_active_weight > 0:
        composite = sum(
            active_scores[dim] * (active_weights[dim] / total_active_weight)
            for dim in active_scores
        )
    else:
        composite = 0.0
    
    # Count objections and other metadata
    objection_count = sum(1 for t in turns if t.get("contains_objection"))
    trust_signal_count = sum(1 for t in turns if t.get("contains_trust_signal"))
    cross_sell_count = sum(1 for t in turns if t.get("contains_cross_sell"))
    contradiction_count = sum(1 for t in turns if t.get("contradicts_persona"))
    
    return {
        "dimensions": scores,
        "composite_score": round(composite, 3),
        "final_outcome": final_outcome,
        "turn_count": len(transcript),
        "metadata": {
            "objection_count": objection_count,
            "trust_signal_count": trust_signal_count,
            "cross_sell_attempts": cross_sell_count,
            "contradiction_count": contradiction_count,
        },
        "turn_analysis": turns,
        "analysis_failed": False,
    }


# ──────────────────────────────────────────────
# Batch Scorer
# ──────────────────────────────────────────────

def score_simulation_batch(
    interviews: List[Dict[str, Any]],
    model: str,
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Score all interviews in a simulation batch.
    
    Args:
        interviews: List of interview result dicts (each containing 'transcript' and 'persona').
        model: LLM model for turn analysis.
        weights: Optional custom weights.
    
    Returns:
        A dict with per-conversation scores, aggregate scores, and dimension breakdowns.
    """
    logger.info("=== Scoring Engine: Scoring %d conversations ===", len(interviews))
    
    conversation_scores = []
    
    for i, interview in enumerate(interviews):
        if not interview:
            continue
        
        transcript = interview.get("transcript", [])
        persona = interview.get("persona", {})
        
        if not transcript:
            logger.warning("Interview %d has no transcript — skipping", i)
            continue
        
        logger.info("Scoring conversation %d/%d...", i + 1, len(interviews))
        score = score_conversation(transcript, persona, model, weights)
        score["interview_index"] = i
        score["persona_name"] = persona.get("name", f"Persona {i}")
        score["archetype"] = persona.get("archetype", "unknown")
        conversation_scores.append(score)
    
    # Calculate aggregate scores
    aggregates = _calculate_aggregates(conversation_scores)
    
    result = {
        "conversation_scores": conversation_scores,
        "aggregates": aggregates,
        "total_conversations": len(conversation_scores),
        "scoring_weights": weights or DEFAULT_WEIGHTS,
    }
    
    logger.info("=== Scoring Engine: Complete (composite avg: %.3f) ===",
                 aggregates.get("composite_score_avg", 0))
    
    return result


def _calculate_aggregates(scores: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate aggregate statistics across all scored conversations."""
    if not scores:
        return {}
    
    n = len(scores)
    
    # Composite score stats
    composites = [s["composite_score"] for s in scores]
    
    # Per-dimension averages (excluding -1.0 / N/A values)
    dimension_avgs = {}
    dimension_names = [
        "objection_bypass_rate", "attribute_consistency", "turns_to_resolution",
        "trust_signal_hit_rate", "cross_sell_success_rate", "conversion",
        "sentiment_velocity",
    ]
    
    for dim in dimension_names:
        values = [s["dimensions"][dim] for s in scores if s["dimensions"].get(dim, -1) >= 0]
        if values:
            dimension_avgs[dim] = {
                "avg": round(sum(values) / len(values), 3),
                "min": round(min(values), 3),
                "max": round(max(values), 3),
                "n": len(values),
            }
    
    # Conversion rate
    conversions = sum(1 for s in scores if s["final_outcome"] == "success")
    
    # Outcome distribution
    outcomes = {}
    for s in scores:
        outcome = s.get("final_outcome", "unclear")
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    
    # Per-archetype breakdown
    archetype_scores = {}
    for s in scores:
        arch = s.get("archetype", "unknown")
        if arch not in archetype_scores:
            archetype_scores[arch] = []
        archetype_scores[arch].append(s["composite_score"])
    
    archetype_avgs = {
        arch: round(sum(vals) / len(vals), 3)
        for arch, vals in archetype_scores.items()
    }
    
    return {
        "composite_score_avg": round(sum(composites) / n, 3),
        "composite_score_min": round(min(composites), 3),
        "composite_score_max": round(max(composites), 3),
        "dimension_averages": dimension_avgs,
        "conversion_rate": round(conversions / n, 3),
        "outcome_distribution": outcomes,
        "archetype_averages": archetype_avgs,
    }


# ──────────────────────────────────────────────
# Report Generator
# ──────────────────────────────────────────────

def generate_score_report(scoring_result: Dict[str, Any], output_dir: str) -> str:
    """
    Generate a human-readable Markdown report from the scoring results.
    
    Args:
        scoring_result: The output from score_simulation_batch.
        output_dir: Directory to save the report.
    
    Returns:
        Path to the generated report file.
    """
    agg = scoring_result.get("aggregates", {})
    scores = scoring_result.get("conversation_scores", [])
    
    lines = [
        "# Simulation Scoring Report",
        "",
        "## Composite Score",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| **Average** | **{agg.get('composite_score_avg', 0):.3f}** |",
        f"| Min | {agg.get('composite_score_min', 0):.3f} |",
        f"| Max | {agg.get('composite_score_max', 0):.3f} |",
        f"| Conversations Scored | {scoring_result.get('total_conversations', 0)} |",
        f"| Conversion Rate | {agg.get('conversion_rate', 0):.1%} |",
        "",
        "## Dimension Breakdown",
        "",
        "| Dimension | Average | Min | Max | N |",
        "|-----------|---------|-----|-----|---|",
    ]
    
    for dim, stats in agg.get("dimension_averages", {}).items():
        dim_label = dim.replace("_", " ").title()
        lines.append(
            f"| {dim_label} | {stats['avg']:.3f} | {stats['min']:.3f} | {stats['max']:.3f} | {stats['n']} |"
        )
    
    lines.extend([
        "",
        "## Outcome Distribution",
        "",
        "| Outcome | Count | % |",
        "|---------|-------|---|",
    ])
    
    total = scoring_result.get("total_conversations", 1)
    for outcome, count in agg.get("outcome_distribution", {}).items():
        lines.append(f"| {outcome.title()} | {count} | {count/total:.1%} |")
    
    lines.extend([
        "",
        "## Archetype Performance",
        "",
        "| Archetype | Avg Composite Score |",
        "|-----------|-------------------|",
    ])
    
    for arch, avg in sorted(agg.get("archetype_averages", {}).items(), key=lambda x: -x[1]):
        lines.append(f"| {arch} | {avg:.3f} |")
    
    # Identify weakest dimensions
    dim_avgs = agg.get("dimension_averages", {})
    if dim_avgs:
        sorted_dims = sorted(dim_avgs.items(), key=lambda x: x[1]["avg"])
        weakest = sorted_dims[0]
        strongest = sorted_dims[-1]
        
        lines.extend([
            "",
            "## Key Findings",
            "",
            f"**Strongest Dimension:** {weakest[0].replace('_', ' ').title()} — "
            f"avg {strongest[1]['avg']:.3f}",
            "",
            f"**Weakest Dimension:** {weakest[0].replace('_', ' ').title()} — "
            f"avg {weakest[1]['avg']:.3f}",
            "",
            "**Recommendation:** Focus the next iteration on improving the weakest dimension. "
            "Revise the agent playbook, persona definitions, or trigger framing to address this gap.",
        ])
    
    report_text = "\n".join(lines)
    
    # Save
    report_path = os.path.join(output_dir, "scoring_report.md")
    try:
        os.makedirs(output_dir, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_text)
        logger.info("Saved scoring report to: %s", report_path)
    except IOError as e:
        logger.error("Failed to save scoring report: %s", e)
    
    # Also save raw scores as JSON
    json_path = os.path.join(output_dir, "scoring_results.json")
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(scoring_result, f, indent=2, default=str)
        logger.info("Saved raw scores to: %s", json_path)
    except IOError as e:
        logger.error("Failed to save raw scores: %s", e)
    
    return report_path
