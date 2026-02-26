"""
Research Engine — Autonomous World Model Generator

When a simulation is run for a new product/industry without a pre-built world model,
this engine uses the LLM to generate a structured knowledge base covering:
  - Industry overview and market size
  - Key players and competitive landscape
  - Common tools and technology stack
  - Buyer behavior patterns
  - Retention/churn benchmarks (where applicable)
  - Pricing norms and budget expectations

This is a "good enough to start" world model. For higher accuracy, users should
provide their own researched world model file.
"""
from typing import Dict, Any

from engines.llm_client import chat_completion


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

    print("  Generating world model for target market...")
    response = chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model=config["llm_model"],
        temperature=0.4,
        max_tokens=6000,
    )

    print("  World model generated.")
    return response


def ensure_world_model(config: Dict[str, Any]) -> str:
    """
    Ensure a world model exists for the simulation.
    If a world_model file is provided in the config, load it.
    Otherwise, generate one using the LLM.

    Returns the world model text and saves it to the output directory.
    """
    import os
    from config import load_context_file

    world_model = load_context_file(config.get("world_model_path"))

    if world_model:
        print("  Using provided world model file.")
        return world_model

    print("  No world model file provided. Generating one automatically...")
    world_model = generate_world_model(config)

    # Save the generated world model for reference
    output_dir = config.get("output_dir", ".")
    os.makedirs(output_dir, exist_ok=True)
    wm_path = os.path.join(output_dir, "generated_world_model.md")
    with open(wm_path, "w") as f:
        f.write(world_model)
    print(f"  Saved generated world model to: {wm_path}")

    # Update the config so the persona engine can use it
    config["_generated_world_model"] = world_model

    return world_model
