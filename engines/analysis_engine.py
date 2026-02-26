"""
Analysis Engine — Product-Agnostic (Hardened)

Analyzes interview transcripts and produces a McKinsey-grade insights report.
Handles both assumption-validation runs and tactical-question runs.

Hardening improvements:
  - Proper structured logging (no print statements)
  - Robust JSON parsing with multi-strategy fallbacks
  - Error boundaries per batch (failed batches don't crash analysis)
  - Graceful degradation (partial analysis still produces a report)
  - Memory-efficient batch processing
"""
import asyncio
import json
from typing import List, Dict, Any, Optional

from engines.logging_config import get_logger
from engines.llm_client import (
    get_async_client, async_chat_completion,
    LLMRetryExhausted, LLMResponseEmpty,
)
from engines.json_parser import parse_llm_json, JSONParseError

logger = get_logger(__name__)


async def _extract_insights_batch(
    client,
    interviews: List[Dict],
    config: Dict[str, Any],
    batch_number: int = 1,
) -> Dict:
    """
    Extract structured insights from a batch of interviews.

    Returns a default empty structure on failure (graceful degradation).
    """
    model = config["llm_model"]
    questions = config.get("questions", [])
    assumptions = config.get("assumptions", [])

    items_block = ""
    if assumptions:
        items_block += "## ASSUMPTIONS BEING TESTED\n" + "\n".join(f"- {a}" for a in assumptions) + "\n\n"
    if questions:
        items_block += "## QUESTIONS BEING EXPLORED\n" + "\n".join(f"- {q}" for q in questions) + "\n\n"

    # Build transcript summaries
    transcript_texts = []
    for interview in interviews:
        persona = interview["persona"]
        lines = [
            f"### {persona.get('name', 'Unknown')} — {persona.get('title', 'N/A')} "
            f"at {persona.get('company_type', 'N/A')} ({persona.get('industry', 'N/A')})"
        ]
        lines.append(
            f"Archetype: {persona.get('archetype_name', 'N/A')} | "
            f"Disposition: {persona.get('disposition', 'N/A')} | "
            f"Skepticism: {persona.get('skepticism_score', 'N/A')}/10"
        )
        for entry in interview.get("transcript", []):
            if entry.get("role") == "error":
                lines.append(f"[Turn {entry.get('turn', '?')} failed]")
            else:
                role = "Interviewer" if entry["role"] == "interviewer" else persona.get("name", "Prospect")
                lines.append(f"{role}: {entry['content']}")
        transcript_texts.append("\n".join(lines))

    all_transcripts = "\n\n---\n\n".join(transcript_texts)

    system_prompt = f"""You are a senior strategy analyst at a top-tier consulting firm.
Your job is to extract structured insights from simulated customer interviews.

{items_block}

## CRITICAL RULES
1. Extract ONLY what was actually said in the interviews. Do NOT invent data or statistics.
2. If a persona expressed a specific sentiment, quote them directly.
3. Rate each assumption/question on a 1-5 scale based on the evidence in these interviews.
4. Flag any responses that seem sycophantic (agreeing too easily without substance).
5. Identify the most surprising or counterintuitive finding.

## OUTPUT FORMAT
Return a JSON object with:
- "insights": Array of objects, one per assumption/question:
  - "item": The assumption or question text
  - "validation_score": 1-5 (1=invalidated, 5=strongly validated)
  - "evidence_for": Array of specific quotes/evidence supporting it
  - "evidence_against": Array of specific quotes/evidence contradicting it
  - "nuance": Key caveats or conditions
  - "segment_differences": How different archetypes/segments responded differently
- "emergent_themes": Array of unexpected themes that emerged across interviews
- "strongest_objections": Array of the most compelling objections raised
- "sycophancy_flags": Array of any responses that seemed artificially positive
- "key_quotes": Array of the 5 most insightful direct quotes

Return ONLY the JSON object."""

    empty_result = {
        "insights": [],
        "emergent_themes": [],
        "strongest_objections": [],
        "sycophancy_flags": [],
        "key_quotes": [],
    }

    try:
        response = await async_chat_completion(
            client=client,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Analyze these {len(interviews)} interview transcripts:\n\n{all_transcripts}"},
            ],
            model=model,
            temperature=0.3,
            max_tokens=6000,
        )

        result = parse_llm_json(
            text=response,
            expected_type=dict,
            context=f"insight extraction batch {batch_number}",
        )

        # Validate expected structure
        if "insights" not in result:
            logger.warning("Batch %d insights missing 'insights' key, using partial result", batch_number)
            result["insights"] = result.get("insights", [])

        return result

    except JSONParseError as e:
        logger.error(
            "JSON parse failed for insight batch %d: %s",
            batch_number, str(e)[:200],
        )
        return empty_result

    except (LLMRetryExhausted, LLMResponseEmpty) as e:
        logger.error(
            "LLM call failed for insight batch %d: %s",
            batch_number, str(e)[:200],
        )
        return empty_result

    except Exception as e:
        logger.error(
            "Unexpected error in insight batch %d: %s",
            batch_number, e,
        )
        return empty_result


async def _generate_report(
    client,
    all_insights: List[Dict],
    config: Dict[str, Any],
    audience_stats: Dict,
) -> str:
    """
    Generate the final McKinsey-grade report from aggregated insights.

    Returns a fallback report on failure.
    """
    model = config["llm_model"]
    product_name = config["product_name"]
    product_description = config["product_description"]
    target_market = config["target_market"]
    questions = config.get("questions", [])
    assumptions = config.get("assumptions", [])

    items_block = ""
    if assumptions:
        items_block += "## ASSUMPTIONS TESTED\n" + "\n".join(f"- {a}" for a in assumptions) + "\n\n"
    if questions:
        items_block += "## QUESTIONS EXPLORED\n" + "\n".join(f"- {q}" for q in questions) + "\n\n"

    # Aggregate insights — truncate if too large for context window
    insights_json = json.dumps(all_insights, indent=2, default=str)
    if len(insights_json) > 30000:
        logger.warning("Insights JSON too large (%d chars), truncating for report generation", len(insights_json))
        insights_json = insights_json[:30000] + "\n... [truncated for length]"

    system_prompt = f"""You are a senior partner at McKinsey & Company writing a strategic insights report.

## PRODUCT: {product_name}
{product_description}

## TARGET MARKET
{target_market}

{items_block}

## AUDIENCE STATISTICS
{json.dumps(audience_stats, indent=2)}

## REPORT REQUIREMENTS
Write a comprehensive, actionable report in Markdown format. Structure it as follows:

1. **Executive Summary** — 3-4 sentences capturing the most important findings.
2. **Methodology** — Brief description of the simulation approach, sample size, and archetype distribution.
3. **Key Findings** — One section per assumption/question with:
   - A clear verdict (Validated / Partially Validated / Invalidated / Inconclusive)
   - Supporting evidence with direct quotes
   - Contradicting evidence with direct quotes
   - Segment-level differences (how different archetypes responded)
   - Strategic implication
4. **Emergent Insights** — Themes that emerged that weren't explicitly tested.
5. **Objection Analysis** — The strongest objections and what they reveal.
6. **Strategic Recommendations** — 3-5 specific, actionable recommendations ranked by priority.
7. **Confidence Assessment** — Honest assessment of where the data is strong vs. where it needs real-world validation.
8. **Suggested Real-World Validation** — 5-8 specific questions to ask in real customer interviews to validate these findings. Note: qualitative research typically reaches saturation at 12-30 interviews.

## CRITICAL RULES
- Use ONLY data from the interviews. Do NOT invent statistics or percentages unless you're counting actual responses.
- When citing percentages, show the math (e.g., "7 of 25 respondents (28%)").
- Quote directly from interviews — use quotation marks and attribute to the persona.
- Be honest about limitations. If the sample is small for a segment, say so.
- Do NOT fabricate industry benchmarks. If you reference external data, clearly label it as context vs. simulation finding.
- Flag any sycophancy concerns in the confidence assessment.
- Write in a direct, authoritative style. No hedging language unless warranted by the data."""

    try:
        response = await async_chat_completion(
            client=client,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Here are the aggregated insights from the simulation:\n\n{insights_json}\n\nWrite the full report."},
            ],
            model=model,
            temperature=0.4,
            max_tokens=8000,
        )

        return response

    except (LLMRetryExhausted, LLMResponseEmpty) as e:
        logger.error("Report generation failed: %s", str(e)[:200])
        return _generate_fallback_report(all_insights, audience_stats, config)

    except Exception as e:
        logger.error("Unexpected error in report generation: %s", e)
        return _generate_fallback_report(all_insights, audience_stats, config)


def _generate_fallback_report(
    all_insights: List[Dict],
    audience_stats: Dict,
    config: Dict[str, Any],
) -> str:
    """Generate a basic report from raw data when LLM report generation fails."""
    logger.warning("Generating fallback report from raw insights data")

    lines = [
        f"# {config['product_name']} — Market Simulation Report (Fallback)",
        "",
        "**Note:** The AI-generated report failed. This is a structured summary of the raw data.",
        "",
        "## Audience Statistics",
        f"- Total interviews: {audience_stats.get('total_interviews', 'N/A')}",
        f"- Average skepticism: {audience_stats.get('avg_skepticism', 'N/A')}/10",
        "",
        "### Disposition Distribution",
    ]

    for disp, count in audience_stats.get("disposition_distribution", {}).items():
        lines.append(f"- {disp}: {count}")

    lines.extend(["", "### Archetype Distribution"])
    for arch, count in audience_stats.get("archetype_distribution", {}).items():
        lines.append(f"- {arch}: {count}")

    lines.extend(["", "## Raw Insights Data", ""])

    for i, batch in enumerate(all_insights):
        if isinstance(batch, dict):
            for insight in batch.get("insights", []):
                lines.append(f"### {insight.get('item', 'Unknown item')}")
                lines.append(f"- Validation score: {insight.get('validation_score', 'N/A')}/5")
                lines.append(f"- Nuance: {insight.get('nuance', 'N/A')}")
                lines.append("")

    lines.extend([
        "",
        "## Key Quotes",
    ])

    for batch in all_insights:
        if isinstance(batch, dict):
            for quote in batch.get("key_quotes", []):
                lines.append(f"- {quote}")

    return "\n".join(lines)


def _compute_audience_stats(interviews: List[Dict]) -> Dict:
    """Compute audience statistics from interview results."""
    dispositions = {}
    archetypes = {}
    industries = {}

    for interview in interviews:
        persona = interview.get("persona", {})
        d = persona.get("disposition", "unknown")
        dispositions[d] = dispositions.get(d, 0) + 1
        a = persona.get("archetype_name", "unknown")
        archetypes[a] = archetypes.get(a, 0) + 1
        ind = persona.get("industry", "unknown")
        industries[ind] = industries.get(ind, 0) + 1

    total = max(len(interviews), 1)
    avg_skepticism = round(
        sum(i.get("persona", {}).get("skepticism_score", 5) for i in interviews) / total, 1
    )

    # Count partial and error interviews
    partial_count = sum(1 for i in interviews if i.get("partial", False))
    error_count = sum(1 for i in interviews if i.get("error", False))

    return {
        "total_interviews": len(interviews),
        "complete_interviews": len(interviews) - partial_count,
        "partial_interviews": partial_count,
        "error_interviews": error_count,
        "disposition_distribution": dispositions,
        "archetype_distribution": archetypes,
        "industry_distribution": industries,
        "avg_skepticism": avg_skepticism,
    }


async def analyze_interviews(
    interviews: List[Dict],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Full analysis pipeline: extract insights in batches, then generate report.

    Graceful degradation: if some batches fail, we still generate a report
    from the batches that succeeded.

    Args:
        interviews: List of interview result dicts from the interview engine.
        config: The fully-resolved simulation config dict.

    Returns:
        Dict with 'report' (markdown string), 'insights' (raw data), and 'audience_stats'.
    """
    if not interviews:
        logger.error("No interviews to analyze")
        return {
            "report": "# No Interviews\n\nNo interviews were completed. Cannot generate a report.",
            "insights": [],
            "audience_stats": {"total_interviews": 0},
        }

    client = get_async_client()

    # Compute audience stats
    audience_stats = _compute_audience_stats(interviews)
    logger.info(
        "Analyzing %d interviews (avg skepticism: %.1f/10)",
        audience_stats["total_interviews"],
        audience_stats["avg_skepticism"],
    )

    # Filter out error-only interviews for analysis
    analyzable = [i for i in interviews if not i.get("error", False)]
    if not analyzable:
        logger.error("All interviews were errors — cannot analyze")
        return {
            "report": "# Analysis Failed\n\nAll interviews encountered errors. No data to analyze.",
            "insights": [],
            "audience_stats": audience_stats,
        }

    # Extract insights in batches of 10
    batch_size = 10
    all_insights = []
    failed_batches = 0
    total_batches = (len(analyzable) + batch_size - 1) // batch_size

    for i in range(0, len(analyzable), batch_size):
        batch = analyzable[i:i + batch_size]
        batch_num = i // batch_size + 1
        logger.info("Analyzing batch %d/%d (%d interviews)...", batch_num, total_batches, len(batch))

        insights = await _extract_insights_batch(client, batch, config, batch_number=batch_num)

        if insights.get("insights") or insights.get("emergent_themes") or insights.get("key_quotes"):
            all_insights.append(insights)
        else:
            failed_batches += 1
            logger.warning("Batch %d returned empty insights", batch_num)

    if failed_batches > 0:
        logger.warning(
            "Analysis: %d/%d insight batches failed or returned empty",
            failed_batches, total_batches,
        )

    # Generate the final report
    logger.info("Generating final report from %d insight batches...", len(all_insights))
    report = await _generate_report(client, all_insights, config, audience_stats)

    # Cleanup
    try:
        await client.close()
    except Exception:
        pass

    logger.info("Analysis complete")

    return {
        "report": report,
        "insights": all_insights,
        "audience_stats": audience_stats,
    }
