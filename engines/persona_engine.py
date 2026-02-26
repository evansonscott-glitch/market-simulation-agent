"""
Persona Generation Engine — Product-Agnostic

Generates a statistically diverse sample of simulated buyer personas
based on the product, target market, archetypes, and world model
provided in the simulation config.

All product-specific knowledge comes from the config — nothing is hardcoded.
"""
import json
import random
from typing import List, Dict, Any, Optional

from engines.llm_client import chat_completion


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

    options = list(weights.keys())
    probs = list(weights.values())
    return random.choices(options, weights=probs, k=1)[0]


def _assign_skepticism_score(archetype: Dict) -> int:
    """Assign a skepticism score (1-10) based on archetype range."""
    low, high = archetype.get("skepticism_range", [4, 7])
    return random.randint(low, high)


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
) -> List[Dict]:
    """Generate a batch of personas for a single archetype via LLM."""

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

## ARCHETYPE: {archetype['name']}
{archetype['description']}

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

    user_prompt = f"Generate {count} unique, diverse personas for the '{archetype['name']}' archetype. Make each one distinct in terms of company size, region, experience level, and current situation. Vary their demographics, backgrounds, and specific circumstances."

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

        # Parse JSON — handle markdown code blocks
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

        personas = json.loads(text)

        # Enrich each persona with simulation metadata
        for persona in personas:
            persona["archetype"] = archetype_key
            persona["archetype_name"] = archetype["name"]
            persona["disposition"] = _assign_disposition(archetype_key, disposition_weights, interaction_context)
            persona["skepticism_score"] = _assign_skepticism_score(archetype)

        return personas

    except json.JSONDecodeError as e:
        print(f"  [WARN] JSON parse error for {archetype['name']} batch: {e}")
        # Try to extract JSON array from the response
        try:
            import re
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                personas = json.loads(match.group())
                for persona in personas:
                    persona["archetype"] = archetype_key
                    persona["archetype_name"] = archetype["name"]
                    persona["disposition"] = _assign_disposition(archetype_key, disposition_weights, interaction_context)
                    persona["skepticism_score"] = _assign_skepticism_score(archetype)
                return personas
        except:
            pass
        print(f"  [ERROR] Could not parse personas for {archetype['name']}. Skipping batch.")
        return []
    except Exception as e:
        print(f"  [ERROR] Failed to generate {archetype['name']} batch: {e}")
        return []


def generate_personas(config: Dict[str, Any]) -> List[Dict]:
    """
    Generate the full audience of simulated personas based on the config.

    Args:
        config: The fully-resolved simulation config dict from config.load_config()

    Returns:
        List of persona dicts ready for the interview engine.
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
    for archetype_key, count in archetype_counts.items():
        if count <= 0:
            continue
        archetype = archetypes[archetype_key]
        print(f"  Generating {count} personas for archetype: {archetype['name']}...")

        batch_size = 10
        for batch_start in range(0, count, batch_size):
            batch_count = min(batch_size, count - batch_start)
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
            )
            all_personas.extend(batch)
            print(f"    Generated {len(batch)} personas (total: {len(all_personas)})")

    print(f"\n  Total personas generated: {len(all_personas)}")

    # Print disposition distribution
    dispositions = {}
    for p in all_personas:
        d = p.get("disposition", "unknown")
        dispositions[d] = dispositions.get(d, 0) + 1
    print(f"  Disposition distribution: {dispositions}")

    avg_skepticism = sum(p.get("skepticism_score", 5) for p in all_personas) / max(len(all_personas), 1)
    print(f"  Average skepticism: {avg_skepticism:.1f}/10")

    return all_personas
