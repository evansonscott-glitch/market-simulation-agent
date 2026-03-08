"""
Market Census Engine — Statistically Valid Sample Frame Generator

Builds a quantitative distribution of the target market using real data sources,
then generates persona "briefs" that match that distribution. This ensures the
simulation sample is representative of the actual market, not just qualitative
archetypes.

Pipeline:
  1. Analyze the world model + config to identify key segmentation variables
  2. Search for real demographic/firmographic data to populate distributions
  3. Build a census.json with validated distributions
  4. Generate persona briefs that match the census distribution

The output is a list of persona briefs, each specifying exact attributes
(e.g., company_size: "1-10", region: "Midwest") that the persona engine
uses to constrain persona generation.
"""
import json
import math
import os
import random
from typing import Dict, Any, List, Optional, Tuple

from engines.logging_config import get_logger
from engines.llm_client import chat_completion, LLMRetryExhausted, LLMResponseEmpty
from engines.json_parser import parse_llm_json, JSONParseError

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Step 1: Identify Segmentation Variables
# ──────────────────────────────────────────────

def _identify_segments(
    product_name: str,
    target_market: str,
    world_model: str,
    archetypes: Dict[str, Any],
    model: str,
) -> Dict[str, Any]:
    """
    Use the world model and config to identify the key segmentation variables
    and their estimated distributions.
    
    Returns a census dict with variable names, categories, and weights.
    """
    archetype_summary = ""
    for key, arch in archetypes.items():
        name = arch.get("name", key)
        desc = arch.get("description", "")[:100]
        weight = arch.get("typical_weight", 0.0)
        archetype_summary += f"- {name} ({weight:.0%}): {desc}\n"

    system_prompt = """You are a market research statistician building a sample frame for a customer simulation.

Your job is to identify the 3-5 most important segmentation variables for the target market and estimate the distribution of each variable based on the world model data provided.

## RULES
1. Choose variables that meaningfully affect buying behavior (not just demographics for demographics' sake).
2. Each variable should have 2-5 categories.
3. The weights for each variable MUST sum to 1.0.
4. Ground your estimates in the world model data. If the world model doesn't have data for a variable, say so in the "data_source" field.
5. Include a "confidence" field for each variable: "high" (grounded in specific data), "medium" (estimated from partial data), "low" (best guess).

## OUTPUT FORMAT
Return a JSON object with this structure:
{
  "variables": [
    {
      "name": "company_size",
      "description": "Number of employees in the company",
      "categories": {
        "1-5 employees": 0.45,
        "6-20 employees": 0.30,
        "21-50 employees": 0.15,
        "51+ employees": 0.10
      },
      "data_source": "World model states 60% of roofing companies have fewer than 10 employees [Source 3]",
      "confidence": "medium"
    }
  ],
  "notes": "Brief notes on methodology and limitations"
}

Return ONLY the JSON object."""

    user_prompt = f"""Build a sample frame for this simulation:

**Product:** {product_name}
**Target Market:** {target_market}

**Existing Archetypes:**
{archetype_summary}

**World Model Data:**
{world_model[:4000]}

Identify the 3-5 most important segmentation variables and estimate their distributions."""

    try:
        response = chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=model,
            temperature=0.3,
            max_tokens=3000,
        )
        
        census = parse_llm_json(response, expected_type=dict, context="census segmentation")
        
        # Validate the structure
        if "variables" not in census:
            raise ValueError("Census missing 'variables' key")
        
        for var in census["variables"]:
            if "categories" not in var:
                raise ValueError(f"Variable '{var.get('name', '?')}' missing 'categories'")
            
            # Normalize weights to sum to 1.0
            total = sum(var["categories"].values())
            if total > 0:
                var["categories"] = {k: v / total for k, v in var["categories"].items()}
        
        logger.info("Identified %d segmentation variables", len(census["variables"]))
        return census
        
    except (JSONParseError, LLMRetryExhausted, LLMResponseEmpty, ValueError) as e:
        logger.error("Census segmentation failed: %s", str(e)[:200])
        return _fallback_census(target_market)


def _fallback_census(target_market: str) -> Dict[str, Any]:
    """Generate a basic fallback census when LLM-based segmentation fails."""
    logger.warning("Using fallback census (LLM segmentation failed)")
    return {
        "variables": [
            {
                "name": "company_size",
                "description": "Size of the organization",
                "categories": {"small": 0.50, "medium": 0.35, "large": 0.15},
                "data_source": "Fallback estimate",
                "confidence": "low",
            },
            {
                "name": "tech_sophistication",
                "description": "Level of technology adoption",
                "categories": {"low": 0.40, "medium": 0.40, "high": 0.20},
                "data_source": "Fallback estimate",
                "confidence": "low",
            },
            {
                "name": "buying_urgency",
                "description": "How urgently they need a solution",
                "categories": {"low": 0.30, "medium": 0.45, "high": 0.25},
                "data_source": "Fallback estimate",
                "confidence": "low",
            },
        ],
        "notes": "Fallback census — LLM segmentation failed. These are generic estimates.",
    }


# ──────────────────────────────────────────────
# Step 2: Generate Persona Briefs
# ──────────────────────────────────────────────

def _weighted_sample(categories: Dict[str, float], n: int) -> List[str]:
    """
    Sample n items from a weighted distribution, ensuring the sample
    approximately matches the target distribution.
    
    Uses deterministic allocation for the bulk, then random sampling
    for the remainder to avoid systematic bias.
    """
    items = list(categories.keys())
    weights = list(categories.values())
    
    # Deterministic allocation: floor of each weight * n
    allocations = {item: int(math.floor(w * n)) for item, w in zip(items, weights)}
    allocated = sum(allocations.values())
    remaining = n - allocated
    
    # Fill remaining slots using weighted random sampling
    if remaining > 0:
        extras = random.choices(items, weights=weights, k=remaining)
        for item in extras:
            allocations[item] += 1
    
    # Build the sample list
    sample = []
    for item, count in allocations.items():
        sample.extend([item] * count)
    
    # Shuffle to avoid ordering bias
    random.shuffle(sample)
    return sample[:n]


def generate_persona_briefs(
    census: Dict[str, Any],
    archetypes: Dict[str, Any],
    persona_count: int,
) -> List[Dict[str, Any]]:
    """
    Generate persona briefs that match the census distribution.
    
    Each brief specifies:
    - An archetype assignment (based on archetype weights)
    - A value for each census variable (based on census distributions)
    
    The persona engine will use these briefs to generate full personas,
    ensuring the simulation sample is statistically representative.
    
    Args:
        census: The census dict from _identify_segments.
        archetypes: The archetype definitions from config.
        persona_count: Number of personas to generate.
    
    Returns:
        A list of persona brief dicts.
    """
    # Sample archetype assignments
    archetype_weights = {}
    for key, arch in archetypes.items():
        archetype_weights[key] = arch.get("typical_weight", 1.0 / len(archetypes))
    
    # Normalize archetype weights
    total_weight = sum(archetype_weights.values())
    if total_weight > 0:
        archetype_weights = {k: v / total_weight for k, v in archetype_weights.items()}
    
    archetype_assignments = _weighted_sample(archetype_weights, persona_count)
    
    # Sample each census variable
    variable_samples = {}
    for var in census.get("variables", []):
        var_name = var["name"]
        categories = var["categories"]
        variable_samples[var_name] = _weighted_sample(categories, persona_count)
    
    # Build persona briefs
    briefs = []
    for i in range(persona_count):
        brief = {
            "persona_index": i,
            "archetype_key": archetype_assignments[i],
            "archetype_name": archetypes[archetype_assignments[i]].get("name", archetype_assignments[i]),
        }
        
        # Add census variable values
        for var_name, samples in variable_samples.items():
            brief[var_name] = samples[i]
        
        briefs.append(brief)
    
    # Log distribution summary
    logger.info("Generated %d persona briefs", len(briefs))
    _log_distribution_summary(briefs, archetype_weights, census)
    
    return briefs


def _log_distribution_summary(
    briefs: List[Dict[str, Any]],
    archetype_weights: Dict[str, float],
    census: Dict[str, Any],
) -> None:
    """Log a summary of the actual vs. target distributions."""
    # Archetype distribution
    archetype_counts = {}
    for brief in briefs:
        key = brief["archetype_key"]
        archetype_counts[key] = archetype_counts.get(key, 0) + 1
    
    n = len(briefs)
    logger.info("--- Distribution Summary ---")
    logger.info("Archetype distribution (actual vs target):")
    for key, count in sorted(archetype_counts.items()):
        actual_pct = count / n
        target_pct = archetype_weights.get(key, 0)
        logger.info("  %s: %.1f%% (target: %.1f%%)", key, actual_pct * 100, target_pct * 100)
    
    # Census variable distributions
    for var in census.get("variables", []):
        var_name = var["name"]
        var_counts = {}
        for brief in briefs:
            val = brief.get(var_name, "unknown")
            var_counts[val] = var_counts.get(val, 0) + 1
        
        logger.info("%s distribution:", var_name)
        for val, count in sorted(var_counts.items()):
            actual_pct = count / n
            target_pct = var["categories"].get(val, 0)
            logger.info("  %s: %.1f%% (target: %.1f%%)", val, actual_pct * 100, target_pct * 100)


# ──────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────

def build_census(config: Dict[str, Any], world_model: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Build a market census and generate persona briefs.
    
    This is the main entry point for the census engine.
    
    Args:
        config: The fully-resolved simulation config dict.
        world_model: The world model text (from research engine v2).
    
    Returns:
        A tuple of (census_dict, persona_briefs_list).
    """
    product_name = config["product_name"]
    target_market = config["target_market"]
    archetypes = config.get("archetypes", {})
    persona_count = config.get("persona_count", 30)
    model = config.get("llm_model", "gemini-2.5-flash")
    
    logger.info("=== Market Census Engine: Building sample frame ===")
    
    # Step 1: Identify segmentation variables
    census = _identify_segments(product_name, target_market, world_model, archetypes, model)
    
    # Step 2: Generate persona briefs
    briefs = generate_persona_briefs(census, archetypes, persona_count)
    
    # Save census to output dir
    output_dir = config.get("output_dir", ".")
    try:
        os.makedirs(output_dir, exist_ok=True)
        
        census_path = os.path.join(output_dir, "census.json")
        with open(census_path, "w", encoding="utf-8") as f:
            json.dump(census, f, indent=2)
        logger.info("Saved census to: %s", census_path)
        
        briefs_path = os.path.join(output_dir, "persona_briefs.json")
        with open(briefs_path, "w", encoding="utf-8") as f:
            json.dump(briefs, f, indent=2)
        logger.info("Saved persona briefs to: %s", briefs_path)
        
    except IOError as e:
        logger.error("Failed to save census files: %s", e)
    
    logger.info("=== Market Census Engine: Complete (%d variables, %d briefs) ===",
                 len(census.get("variables", [])), len(briefs))
    
    return census, briefs
