"""
Analysis Engine — Product-Agnostic

Analyzes interview transcripts and produces a McKinsey-grade insights report.
Handles both assumption-validation runs and tactical-question runs.

All product-specific knowledge comes from the config — nothing is hardcoded.
"""
import asyncio
import json
from typing import List, Dict, Any

from engines.llm_client import get_async_client, async_chat_completion


async def _extract_insights_batch(
    client,
    interviews: List[Dict],
    config: Dict[str, Any],
) -> List[Dict]:
    """Extract structured insights from a batch of interviews."""
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
        lines = [f"### {persona.get('name', 'Unknown')} — {persona.get('title', 'N/A')} at {persona.get('company_type', 'N/A')} ({persona.get('industry', 'N/A')})"]
        lines.append(f"Archetype: {persona.get('archetype_name', 'N/A')} | Disposition: {persona.get('disposition', 'N/A')} | Skepticism: {persona.get('skepticism_score', 'N/A')}/10")
        for entry in interview.get("transcript", []):
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

        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            elif "```" in text:
                text = text[:text.rfind("```")]
            text = text.strip()
            if text.startswith("json"):
                text = text[4:].strip()

        return json.loads(text)

    except Exception as e:
        print(f"  [ERROR] Insight extraction failed: {e}")
        return {"insights": [], "emergent_themes": [], "strongest_objections": [], "sycophancy_flags": [], "key_quotes": []}


async def _generate_report(
    client,
    all_insights: List[Dict],
    config: Dict[str, Any],
    audience_stats: Dict,
) -> str:
    """Generate the final McKinsey-grade report from aggregated insights."""
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

    # Aggregate insights
    insights_json = json.dumps(all_insights, indent=2, default=str)

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


async def analyze_interviews(
    interviews: List[Dict],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Full analysis pipeline: extract insights in batches, then generate report.

    Args:
        interviews: List of interview result dicts from the interview engine.
        config: The fully-resolved simulation config dict.

    Returns:
        Dict with 'report' (markdown string), 'insights' (raw data), and 'audience_stats'.
    """
    client = get_async_client()

    # Compute audience stats
    dispositions = {}
    archetypes = {}
    industries = {}
    for interview in interviews:
        persona = interview["persona"]
        d = persona.get("disposition", "unknown")
        dispositions[d] = dispositions.get(d, 0) + 1
        a = persona.get("archetype_name", "unknown")
        archetypes[a] = archetypes.get(a, 0) + 1
        ind = persona.get("industry", "unknown")
        industries[ind] = industries.get(ind, 0) + 1

    audience_stats = {
        "total_interviews": len(interviews),
        "disposition_distribution": dispositions,
        "archetype_distribution": archetypes,
        "industry_distribution": industries,
        "avg_skepticism": round(
            sum(i["persona"].get("skepticism_score", 5) for i in interviews) / max(len(interviews), 1), 1
        ),
    }

    # Extract insights in batches of 10
    batch_size = 10
    all_insights = []
    for i in range(0, len(interviews), batch_size):
        batch = interviews[i:i + batch_size]
        print(f"  Analyzing batch {i // batch_size + 1}/{(len(interviews) + batch_size - 1) // batch_size}...")
        insights = await _extract_insights_batch(client, batch, config)
        all_insights.append(insights)

    # Generate the final report
    print("  Generating final report...")
    report = await _generate_report(client, all_insights, config, audience_stats)

    await client.close()

    return {
        "report": report,
        "insights": all_insights,
        "audience_stats": audience_stats,
    }
