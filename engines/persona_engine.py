"""
Persona Generation Engine — Product-Agnostic (Hardened)

Generates a statistically diverse sample of simulated buyer personas
based on the product, target market, archetypes, and world model
provided in the simulation config.

Hardening improvements:
  - Proper structured logging (no print statements)
  - Robust JSON parsing with multi-strategy fallbacks
  - Graceful degradation (failed batches are skipped, not fatal)
  - Error boundaries around each batch
  - Input validation
"""
import json
import random
from typing import List, Dict, Any, Optional

from engines.logging_config import get_logger
from engines.llm_client import chat_completion, LLMRetryExhausted, LLMResponseEmpty
from engines.json_parser import parse_llm_json, JSONParseError

logger = get_logger(__name__)


def _assign_disposition(archetype_key: str, disposition_weights: Dict, interaction_context: str) -> str:
    """Assign a disposition based on weighted random selection."""
    weights = dict(disposition_weights.get(interaction_context, disposition_weights.get("blended", {})))

    # Shift distribution based on archetype
    if archetype_key == "red_team_skeptic":
        weights = {"enthusiastic": 0.0, "open": 0.05, "cautious": 0.15, "skeptical": 0.40, "resistant": 0.40}
    elif archetype_key == "strategic_enterprise":
        weights = {"enthusiastic": 0.05, "open": 0.15, "cautious": 0.35, "skeptical": 0.30, "resistant": 0.15}
    elif archetype_key == "overwhelmed_founder":
        if interaction_context == "warm_demo":
            weights = {"enthusiastic": 0.18, "open": 0.28, "cautious": 0.28, "skeptical": 0.18, "resistant": 0.08}
        else:
            weights = {"enthusiastic": 0.15, "open": 0.25, "cautious": 0.30, "skeptical": 0.20, "resistant": 0.10}

    if not weights:
        logger.warning("No disposition weights found for context '%s', using uniform", interaction_context)
        weights = {"enthusiastic": 0.2, "open": 0.2, "cautious": 0.2, "skeptical": 0.2, "resistant": 0.2}

    options = list(weights.keys())
    probs = list(weights.values())
    return random.choices(options, weights=probs, k=1)[0]


def _assign_skepticism_score(archetype: Dict) -> int:
    """Assign a skepticism score (1-10) based on archetype range."""
    skepticism_range = archetype.get("skepticism_range", [4, 7])
    if isinstance(skepticism_range, (list, tuple)) and len(skepticism_range) == 2:
        low, high = int(skepticism_range[0]), int(skepticism_range[1])
        low = max(1, min(10, low))
        high = max(low, min(10, high))
        return random.randint(low, high)
    return random.randint(4, 7)


def _enrich_persona(persona: Dict, archetype_key: str, archetype: Dict,
                    disposition_weights: Dict, interaction_context: str) -> Dict:
    """Add simulation metadata to a persona dict."""
    persona["archetype"] = archetype_key
    persona["archetype_name"] = archetype.get("name", archetype_key)
    persona["disposition"] = _assign_disposition(archetype_key, disposition_weights, interaction_context)
    persona["skepticism_score"] = _assign_skepticism_score(archetype)
    return persona


def _validate_persona(persona: Dict) -> bool:
    """Basic validation that a persona dict has required fields."""
    required_fields = ["name", "title"]
    for field in required_fields:
        if field not in persona or not persona[field]:
            return False
    return True


def _generate_persona_batch(
    archetype_key: str,
    archetype: Dict,
    count: int,
    product_description: str,
    target_market: str,
    world_model: str,
    real_customer_data: str,
    interaction_context: str,
    disposition_weights: Dict,
    model: str,
    batch_number: int = 1,
) -> List[Dict]:
    """
    Generate a batch of personas for a single archetype via LLM.

    Returns an empty list on failure (graceful degradation).
    """
    archetype_name = archetype.get("name", archetype_key)

    system_prompt = f"""You are a market research persona generator for the Philo Ventures Market Simulator.

Your job is to create realistic, diverse buyer personas for a simulated customer interview.

## PRODUCT BEING TESTED
{product_description}

## TARGET MARKET
{target_market}

## VERIFIED MARKET DATA (use this for grounding — do NOT invent statistics)
{world_model[:6000] if world_model else "No verified market data available."}

## REAL CUSTOMER DATA (use this to calibrate realism)
{real_customer_data[:3000] if real_customer_data else "No real customer data available."}

## ARCHETYPE: {archetype_name}
{archetype.get('description', '')}

Typical behaviors: {json.dumps(archetype.get('behaviors', []))}
Common objections: {json.dumps(archetype.get('common_objections', []))}

## CRITICAL ANTI-SYCOPHANCY INSTRUCTIONS
- These personas will be interviewed about the product. They must behave REALISTICALLY.
- Most real people are NOT enthusiastic about being pitched a new product.
- Personas MUST have genuine, specific reasons for their skepticism — not generic pushback.
- Do NOT create personas who are predisposed to agree with the interviewer.
- Each persona should have a SPECIFIC current situation that shapes their reaction.
- Include personas who would genuinely say "no" and mean it.

## OUTPUT FORMAT
Return a JSON array of {count} persona objects. Each must have:
- "name": Full name
- "title": Job title
- "company_type": Type/size of company
- "company_size": Approximate employee count or revenue
- "industry": Specific industry/vertical
- "region": Geographic region
- "years_experience": Years in role/industry
- "current_tools": What tools/processes they currently use for the problem area
- "pain_points": List of 2-3 specific pain points (or "none" if they don't feel the pain)
- "priorities": Their top 3 business priorities right now
- "budget_sensitivity": "low" | "medium" | "high"
- "tech_sophistication": "low" | "medium" | "high"
- "personality_notes": 2-3 sentences about how they communicate and make decisions

Return ONLY the JSON array, no other text."""

    user_prompt = (
        f"Generate {count} unique, diverse personas for the '{archetype_name}' archetype. "
        f"Make each one distinct in terms of company size, region, experience level, and "
        f"current situation. Vary their demographics, backgrounds, and specific circumstances."
    )

    try:
        response = chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=model,
            temperature=0.9,
            max_tokens=8000,
        )

        # Parse with robust multi-strategy parser
        personas = parse_llm_json(
            text=response,
            expected_type=list,
            context=f"persona batch for {archetype_name} (batch {batch_number})",
        )

        # Validate and enrich each persona
        valid_personas = []
        for persona in personas:
            if not isinstance(persona, dict):
                logger.warning("Skipping non-dict persona in %s batch", archetype_name)
                continue
            if not _validate_persona(persona):
                logger.warning("Skipping invalid persona (missing name/title) in %s batch", archetype_name)
                continue
            persona = _enrich_persona(persona, archetype_key, archetype, disposition_weights, interaction_context)
            valid_personas.append(persona)

        if len(valid_personas) < count:
            logger.warning(
                "Generated %d/%d valid personas for %s batch %d",
                len(valid_personas), count, archetype_name, batch_number,
            )

        return valid_personas

    except JSONParseError as e:
        logger.error(
            "JSON parse failed for %s batch %d after all strategies: %s",
            archetype_name, batch_number, str(e)[:200],
        )
        return []

    except (LLMRetryExhausted, LLMResponseEmpty) as e:
        logger.error(
            "LLM call failed for %s batch %d: %s",
            archetype_name, batch_number, str(e)[:200],
        )
        return []

    except Exception as e:
        logger.error(
            "Unexpected error generating %s batch %d: %s",
            archetype_name, batch_number, e,
        )
        return []


def generate_personas(config: Dict[str, Any]) -> List[Dict]:
    """
    Generate the full audience of simulated personas based on the config.

    Graceful degradation: if some batches fail, we continue with what we have.
    The caller can check the returned count against the requested count.

    Args:
        config: The fully-resolved simulation config dict from config.load_config()

    Returns:
        List of persona dicts ready for the interview engine.

    Raises:
        ValueError: If no personas could be generated at all.
    """
    from config import load_context_file

    product_description = config["product_description"]
    target_market = config["target_market"]
    archetypes = config["archetypes"]
    disposition_weights = config["disposition_weights"]
    interaction_context = config["interaction_context"]
    sample_size = config["persona_count"]
    model = config["llm_model"]

    # Load context files
    world_model = load_context_file(config.get("world_model_path"))
    real_customer_data = load_context_file(config.get("customer_list_path"))
    transcripts = load_context_file(config.get("transcripts_path"))
    if transcripts:
        real_customer_data += f"\n\n## Sales Transcript Excerpts\n{transcripts[:5000]}"

    # Calculate counts per archetype
    archetype_weights = {k: v.get("typical_weight", 1.0 / len(archetypes)) for k, v in archetypes.items()}
    total_weight = sum(archetype_weights.values())
    if total_weight == 0:
        total_weight = 1.0
    archetype_weights = {k: v / total_weight for k, v in archetype_weights.items()}

    archetype_counts = {}
    remaining = sample_size
    sorted_archetypes = sorted(archetype_weights.items(), key=lambda x: x[1], reverse=True)
    for i, (key, weight) in enumerate(sorted_archetypes):
        if i == len(sorted_archetypes) - 1:
            archetype_counts[key] = remaining
        else:
            count = round(sample_size * weight)
            archetype_counts[key] = count
            remaining -= count

    # Generate personas in batches per archetype
    all_personas = []
    failed_batches = 0
    total_batches = 0

    for archetype_key, count in archetype_counts.items():
        if count <= 0:
            continue
        archetype = archetypes[archetype_key]
        archetype_name = archetype.get("name", archetype_key)
        logger.info("Generating %d personas for archetype: %s", count, archetype_name)

        batch_size = 10
        batch_num = 0
        for batch_start in range(0, count, batch_size):
            batch_count = min(batch_size, count - batch_start)
            batch_num += 1
            total_batches += 1

            batch = _generate_persona_batch(
                archetype_key=archetype_key,
                archetype=archetype,
                count=batch_count,
                product_description=product_description,
                target_market=target_market,
                world_model=world_model,
                real_customer_data=real_customer_data,
                interaction_context=interaction_context,
                disposition_weights=disposition_weights,
                model=model,
                batch_number=batch_num,
            )

            if not batch:
                failed_batches += 1
                logger.warning(
                    "Batch %d for %s returned 0 personas — will continue with remaining",
                    batch_num, archetype_name,
                )
            else:
                all_personas.extend(batch)
                logger.info(
                    "  %s batch %d: %d personas (running total: %d)",
                    archetype_name, batch_num, len(batch), len(all_personas),
                )

    # Summary statistics
    if not all_personas:
        raise ValueError(
            f"Failed to generate any personas. All {total_batches} batches failed. "
            "Check your API key, model availability, and network connection."
        )

    if failed_batches > 0:
        logger.warning(
            "Persona generation: %d/%d batches failed. Generated %d/%d requested personas.",
            failed_batches, total_batches, len(all_personas), sample_size,
        )

    # Log distribution stats
    dispositions = {}
    for p in all_personas:
        d = p.get("disposition", "unknown")
        dispositions[d] = dispositions.get(d, 0) + 1

    avg_skepticism = sum(p.get("skepticism_score", 5) for p in all_personas) / len(all_personas)

    logger.info("Total personas generated: %d/%d", len(all_personas), sample_size)
    logger.info("Disposition distribution: %s", dispositions)
    logger.info("Average skepticism: %.1f/10", avg_skepticism)

    return all_personas
