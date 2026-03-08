"""
Loop 2: Revised Simulation — Targeting Weakest Dimensions

Baseline (Loop 1):
  - Composite: 0.326
  - Trust Signal Hit Rate: 0.000
  - Objection Bypass Rate: 0.217
  - Turns to Resolution: 0.120
  - Conversion: 10%

Changes for Loop 2:
  1. INTERVIEWER: Add trust signal deployment instructions — when persona raises
     security/trust concerns, respond with specific trust signals (SOC 2, encryption,
     compliance, team credentials, etc.)
  2. INTERVIEWER: Add objection handling framework — acknowledge, empathize, address
     with specifics, then redirect to value
  3. INTERVIEWER: Add resolution-driving instructions — push for clear yes/no/maybe
     in final 2 turns instead of leaving conversations "unclear"
  4. PERSONA: Increase turn budget to 6 (from 4) to give more room for resolution
"""
import asyncio
import json
import os
import sys
import time
import logging
from unittest.mock import patch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("loop2")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config
from engines.research_engine_v2 import generate_world_model_v2
from engines.market_census import build_census
from engines.persona_engine import generate_personas
from engines.interview_engine import run_interviews, _build_interviewer_system_prompt
from engines.scoring_engine import score_simulation_batch, generate_score_report


# ──────────────────────────────────────────────
# REVISED INTERVIEWER PROMPT (Loop 2)
# ──────────────────────────────────────────────

def _build_interviewer_system_prompt_v2(
    product_description: str,
    questions: list,
    assumptions: list,
    num_turns: int,
) -> str:
    """
    Loop 2 revision: adds trust signal deployment, objection handling
    framework, and resolution-driving instructions.
    """
    items_to_explore = []
    if assumptions:
        items_to_explore.append("## ASSUMPTIONS TO VALIDATE\n" + "\n".join(f"- {a}" for a in assumptions))
    if questions:
        items_to_explore.append("## SPECIFIC QUESTIONS TO EXPLORE\n" + "\n".join(f"- {q}" for q in questions))

    exploration_block = "\n\n".join(items_to_explore) if items_to_explore else "Explore the prospect's needs and reactions to the product."

    return f"""You are a skilled customer discovery interviewer conducting a simulated market research interview.

## THE PRODUCT
{product_description}

{exploration_block}

## INTERVIEW RULES
1. You have {num_turns} turns. Make every question count.
2. Start with an open-ended question about their current situation — do NOT pitch the product immediately.
3. Listen to what they say and follow up on the most interesting threads.
4. If they express skepticism, EXPLORE it — ask "why do you feel that way?" and then ADDRESS it with specifics.
5. If they seem positive, STRESS-TEST it — ask "what would make you NOT buy this?" or "what's the biggest risk?"
6. Do NOT ask leading questions. "Would you agree that X is a problem?" is leading. "How do you handle X today?" is not.
7. Do NOT try to hard-sell. You are gathering information AND building trust.
8. Ask about specifics: budget, timeline, decision process, current tools, past experiences with similar products.
9. If they say something surprising, follow up on it even if it's off-script.
10. Keep questions to 1-2 sentences. Be conversational.

## TRUST SIGNAL DEPLOYMENT (CRITICAL)
When the person raises concerns about SECURITY, DATA PRIVACY, or TRUST in the product, you MUST respond with specific, concrete trust signals. Do NOT just acknowledge the concern — ADDRESS it with facts:

- **Security concerns:** "That's a great question. We're SOC 2 Type 2 certified, all data is encrypted at rest and in transit with AES-256, and we undergo annual third-party penetration testing."
- **Data privacy concerns:** "Your data never leaves your control. We use read-only API connections, don't store raw affiliate data, and you can revoke access at any time."
- **AI accuracy concerns:** "We've built in a confidence score for every alert. If the AI isn't 95%+ confident, it flags it as 'needs review' rather than presenting it as fact. And every alert links directly to the source data so you can verify in one click."
- **Integration concerns:** "We've done 200+ integrations with Impact.com, CJ, and AWIN. The typical setup takes 15 minutes and doesn't require IT involvement."
- **Vendor approval concerns:** "We can provide a pre-built security questionnaire, our SOC 2 report, and a data flow diagram to your IT team upfront to accelerate the review."

Adapt these to the specific concern raised. Be specific, not vague.

## OBJECTION HANDLING FRAMEWORK
When the person raises an objection, follow this pattern:
1. **Acknowledge:** "I completely understand that concern."
2. **Empathize:** Reference their specific situation. "Given that you're managing 5 client programs across different networks, that's a legitimate worry."
3. **Address:** Provide a specific, concrete response (see trust signals above).
4. **Redirect:** Ask a follow-up that moves the conversation forward. "If we could address that security concern, what would be the next thing you'd want to see?"

## RESOLUTION-DRIVING (FINAL 2 TURNS)
In your second-to-last turn, summarize what you've heard and ask: "It sounds like [summary of their key concerns and interests]. Is that a fair characterization?"

In your FINAL turn, ask a direct closing question that forces a clear outcome:
- "Based on everything we've discussed, if we addressed [their top concern], would you be willing to do a pilot?"
- "On a scale of 1-10, how likely would you be to try this in the next 3 months? And what would move that number up?"
- "What would need to be true for you to say yes to a trial?"

Do NOT end the conversation with a vague "thanks for your time." Drive to a clear yes, no, or conditional yes.

Your goal is to understand this person's REAL reaction to the product — positive, negative, or indifferent — while demonstrating that you can address their concerns with substance."""


async def main():
    start_time = time.time()

    # ── Load config ──
    config_path = os.path.join(os.path.dirname(__file__), "examples", "refinery", "config.yaml")
    logger.info("Loading config from: %s", config_path)
    config = load_config(config_path)

    # Same sample size as Loop 1 for fair comparison
    config["persona_count"] = 10
    config["interview_turns"] = 6  # Increased from 4 to give more room for resolution
    config["persona_concurrency"] = 5
    config["interview_concurrency"] = 5

    output_dir = os.path.join(os.path.dirname(__file__), "test_v2_loop2_output")
    os.makedirs(output_dir, exist_ok=True)
    config["output_dir"] = output_dir

    # ── STEP 1: Reuse world model from Loop 1 (no need to re-research) ──
    logger.info("=" * 60)
    logger.info("LOOP 2: Loading world model from Loop 1...")
    logger.info("=" * 60)

    loop1_wm_path = os.path.join(os.path.dirname(__file__), "test_v2_output", "world_model_v2.md")
    with open(loop1_wm_path, "r") as f:
        world_model = f.read()
    logger.info("World model loaded: %d chars", len(world_model))

    # ── STEP 2: Reuse census from Loop 1 ──
    logger.info("=" * 60)
    logger.info("LOOP 2: Loading census from Loop 1...")
    logger.info("=" * 60)

    loop1_briefs_path = os.path.join(os.path.dirname(__file__), "test_v2_output", "persona_briefs.json")
    with open(loop1_briefs_path, "r") as f:
        persona_briefs = json.load(f)
    logger.info("Loaded %d persona briefs", len(persona_briefs))

    # ── STEP 3: Generate NEW personas (different people, same distribution) ──
    logger.info("=" * 60)
    logger.info("LOOP 2: Generating fresh personas...")
    logger.info("=" * 60)

    brief_text = "\n\n## Census-Based Persona Briefs\n\n"
    brief_text += "Each persona should match these pre-assigned attributes:\n\n"
    for brief in persona_briefs:
        attrs = {k: v for k, v in brief.items() if k not in ("persona_index",)}
        brief_text += f"- Persona {brief['persona_index']}: {json.dumps(attrs)}\n"

    enriched_world_model = world_model + brief_text
    config["_generated_world_model"] = enriched_world_model

    personas = generate_personas(config)
    logger.info("Generated %d personas", len(personas))

    # ── STEP 4: Run interviews with REVISED interviewer prompt ──
    logger.info("=" * 60)
    logger.info("LOOP 2: Running interviews with REVISED interviewer prompt...")
    logger.info("=" * 60)

    # Monkey-patch the interviewer prompt builder
    import engines.interview_engine as ie_module
    original_builder = ie_module._build_interviewer_system_prompt
    ie_module._build_interviewer_system_prompt = _build_interviewer_system_prompt_v2

    try:
        interviews = await run_interviews(personas, config)
    finally:
        # Restore original
        ie_module._build_interviewer_system_prompt = original_builder

    successful = [i for i in interviews if i]
    logger.info("Completed %d/%d interviews", len(successful), len(personas))

    # ── STEP 5: Score ──
    logger.info("=" * 60)
    logger.info("LOOP 2: Running objective scoring engine...")
    logger.info("=" * 60)

    scoring_result = score_simulation_batch(
        interviews=successful,
        model=config["llm_model"],
    )

    score_report_path = generate_score_report(scoring_result, output_dir)
    logger.info("Scoring report saved: %s", score_report_path)

    # ── SUMMARY ──
    elapsed = time.time() - start_time
    agg = scoring_result.get("aggregates", {})

    logger.info("=" * 60)
    logger.info("LOOP 2 COMPLETE")
    logger.info("=" * 60)
    logger.info("Total time: %.1f minutes", elapsed / 60)
    logger.info("")
    logger.info("── Scoring Summary (Loop 2 vs Loop 1 baseline) ──")
    logger.info("Composite Score: %.3f (baseline: 0.326)", agg.get("composite_score_avg", 0))
    logger.info("Conversion Rate: %.1f%% (baseline: 10.0%%)", agg.get("conversion_rate", 0) * 100)
    logger.info("")

    loop1_baselines = {
        "Objection Bypass Rate": 0.217,
        "Attribute Consistency": 1.000,
        "Turns To Resolution": 0.120,
        "Trust Signal Hit Rate": 0.000,
        "Conversion": 0.100,
        "Sentiment Velocity": 0.486,
    }

    for dim, stats in agg.get("dimension_averages", {}).items():
        dim_label = dim.replace("_", " ").title()
        baseline = loop1_baselines.get(dim_label, 0)
        delta = stats["avg"] - baseline
        direction = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        logger.info("  %s: %.3f (baseline: %.3f) %s%.3f",
                    dim_label, stats["avg"], baseline, direction, abs(delta))

    logger.info("")
    logger.info("── Output Files ──")
    for fname in sorted(os.listdir(output_dir)):
        fpath = os.path.join(output_dir, fname)
        if os.path.isfile(fpath):
            size = os.path.getsize(fpath)
            logger.info("  %s (%d bytes)", fname, size)

    # Save comparison data for later
    comparison = {
        "loop": 2,
        "changes": [
            "Added trust signal deployment instructions to interviewer prompt",
            "Added objection handling framework (acknowledge, empathize, address, redirect)",
            "Added resolution-driving instructions for final 2 turns",
            "Increased interview turns from 4 to 6",
        ],
        "composite_score": agg.get("composite_score_avg", 0),
        "conversion_rate": agg.get("conversion_rate", 0),
        "dimension_averages": agg.get("dimension_averages", {}),
        "outcome_distribution": agg.get("outcome_distribution", {}),
        "archetype_averages": agg.get("archetype_averages", {}),
    }
    with open(os.path.join(output_dir, "loop2_comparison.json"), "w") as f:
        json.dump(comparison, f, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
