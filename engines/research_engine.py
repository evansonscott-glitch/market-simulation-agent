"""
Research Engine — Autonomous World Model Generator (Hardened)

When a simulation is run for a new product/industry without a pre-built world model,
this engine uses the LLM to generate a structured knowledge base covering:
  - Industry overview and market size
  - Key players and competitive landscape
  - Common tools and technology stack
  - Buyer behavior patterns
  - Retention/churn benchmarks (where applicable)
  - Pricing norms and budget expectations

Hardening improvements:
  - Proper structured logging (no print statements)
  - Error handling with clear error messages
  - Graceful degradation (returns minimal world model on failure)
"""
import os
from typing import Dict, Any

from engines.logging_config import get_logger
from engines.llm_client import chat_completion, LLMRetryExhausted, LLMResponseEmpty

logger = get_logger(__name__)


def generate_world_model(config: Dict[str, Any]) -> str:
    """
    Generate a world model for the target market using LLM knowledge.

    This is used when no world_model file is provided in the config.
    The output is a structured Markdown document that gets injected into
    the persona generation prompts.

    Args:
        config: The fully-resolved simulation config dict.

    Returns:
        A Markdown string containing the world model.

    Raises:
        LLMRetryExhausted: If the LLM call fails after all retries.
    """
    product_name = config["product_name"]
    product_description = config["product_description"]
    target_market = config["target_market"]

    system_prompt = """You are a senior market research analyst preparing a briefing document for a customer simulation.

Your job is to create a comprehensive, factual overview of a specific market that will be used to ground simulated buyer personas in reality.

## CRITICAL RULES
1. Only include information you are confident is accurate. If you're unsure, say "estimated" or "approximate."
2. Do NOT fabricate specific statistics. Use ranges and qualitative descriptions when exact data isn't available.
3. Focus on information that would shape how a BUYER in this market thinks and makes decisions.
4. Include the technology landscape — what tools and platforms are commonly used.
5. Include the competitive landscape — who else is trying to solve similar problems.
6. Include buyer behavior patterns — how decisions are made, who's involved, typical timelines.
7. Include economic context — budget sensitivity, pricing norms, ROI expectations.

## OUTPUT FORMAT
Write a structured Markdown document with the following sections:
1. Industry Overview
2. Market Size and Growth (use ranges if exact data unavailable)
3. Key Players and Competitive Landscape
4. Common Technology Stack / Tools
5. Buyer Personas and Decision-Making Patterns
6. Pricing Norms and Budget Expectations
7. Key Challenges and Pain Points
8. Industry Trends and Tailwinds
9. Data Quality Disclaimer (be honest about what you're confident in vs. estimating)"""

    user_prompt = f"""Create a world model briefing for the following simulation:

**Product:** {product_name}
{product_description}

**Target Market:** {target_market}

Focus on the information that would help generate realistic buyer personas and predict how real people in this market would react to this product."""

    logger.info("Generating world model for target market: %s", target_market[:100])

    try:
        response = chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=config["llm_model"],
            temperature=0.4,
            max_tokens=6000,
        )

        logger.info("World model generated successfully (%d chars)", len(response))
        return response

    except (LLMRetryExhausted, LLMResponseEmpty) as e:
        logger.error("Failed to generate world model: %s", str(e)[:200])
        # Return a minimal fallback world model
        return _generate_fallback_world_model(product_name, target_market)

    except Exception as e:
        logger.error("Unexpected error generating world model: %s", e)
        return _generate_fallback_world_model(product_name, target_market)


def _generate_fallback_world_model(product_name: str, target_market: str) -> str:
    """Generate a minimal world model when the LLM call fails."""
    logger.warning("Using fallback world model (LLM generation failed)")
    return f"""# World Model: {product_name} — {target_market}

**Note:** This is a minimal fallback world model generated because the AI-powered
world model generation failed. The simulation will proceed with limited market context.
For better results, provide a manually-created world model file in your config.

## Industry Overview
Target market: {target_market}

## Data Quality Disclaimer
This is a fallback document with no verified market data. Results from this simulation
should be treated as preliminary and validated with real market research.
"""


def ensure_world_model(config: Dict[str, Any]) -> str:
    """
    Ensure a world model exists for the simulation.
    If a world_model file is provided in the config, load it.
    Otherwise, generate one using the LLM.

    Args:
        config: The fully-resolved simulation config dict.

    Returns:
        The world model text.
    """
    from config import load_context_file

    world_model = load_context_file(config.get("world_model_path"))

    if world_model:
        logger.info("Using provided world model file (%d chars)", len(world_model))
        return world_model

    logger.info("No world model file provided — generating one automatically")
    world_model = generate_world_model(config)

    # Save the generated world model for reference
    output_dir = config.get("output_dir", ".")
    try:
        os.makedirs(output_dir, exist_ok=True)
        wm_path = os.path.join(output_dir, "generated_world_model.md")
        with open(wm_path, "w", encoding="utf-8") as f:
            f.write(world_model)
        logger.info("Saved generated world model to: %s", wm_path)
    except IOError as e:
        logger.error("Failed to save generated world model: %s", e)

    # Update the config so the persona engine can use it
    config["_generated_world_model"] = world_model

    return world_model
