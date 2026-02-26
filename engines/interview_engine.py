"""
Interview Engine — Product-Agnostic

Conducts 5-turn conversational interviews with simulated personas.
Each persona is its own LLM-powered agent that responds in character.
The interviewer adapts its questions based on the persona's responses.

All product-specific knowledge comes from the config — nothing is hardcoded.
"""
import asyncio
import json
from typing import List, Dict, Any

from engines.llm_client import get_async_client, async_chat_completion


def _build_persona_system_prompt(persona: Dict, product_description: str) -> str:
    """Build the system prompt that makes the LLM behave as this persona."""
    return f"""You are role-playing as a specific person in a market research simulation.

## WHO YOU ARE
Name: {persona.get('name', 'Unknown')}
Title: {persona.get('title', 'Unknown')}
Company: {persona.get('company_type', 'Unknown')} ({persona.get('company_size', 'Unknown')})
Industry: {persona.get('industry', 'Unknown')}
Region: {persona.get('region', 'Unknown')}
Experience: {persona.get('years_experience', 'Unknown')} years
Current tools: {persona.get('current_tools', 'Unknown')}
Pain points: {json.dumps(persona.get('pain_points', []))}
Top priorities: {json.dumps(persona.get('priorities', []))}
Budget sensitivity: {persona.get('budget_sensitivity', 'medium')}
Tech sophistication: {persona.get('tech_sophistication', 'medium')}
Personality: {persona.get('personality_notes', '')}

## YOUR DISPOSITION
You are {persona.get('disposition', 'cautious')} about new products.
Your skepticism level is {persona.get('skepticism_score', 5)}/10.

## THE PRODUCT BEING DISCUSSED
{product_description}

## CRITICAL INSTRUCTIONS
1. Stay COMPLETELY in character. Respond as this person would — with their vocabulary, concerns, and decision-making style.
2. Your disposition is {persona.get('disposition', 'cautious')}. This MUST shape every response:
   - "enthusiastic": You see real potential but still have practical questions.
   - "open": You're willing to listen but need convincing. Ask tough questions.
   - "cautious": You're interested but worried about risk, cost, and disruption. Hedge your answers.
   - "skeptical": You doubt this will work for you. Push back on claims. Demand proof.
   - "resistant": You don't think you need this. Be polite but firm in your skepticism.
3. Your skepticism score is {persona.get('skepticism_score', 5)}/10. Higher = harder to convince.
4. DO NOT be a pushover. If the interviewer asks leading questions, don't just agree.
5. If you genuinely wouldn't buy this product, say so clearly and explain why.
6. Reference your SPECIFIC situation — your tools, your team size, your budget, your priorities.
7. Give concrete, specific answers — not vague generalities.
8. If you don't know something, say "I don't know" or "I'd have to think about that."
9. Keep responses to 3-5 sentences. Be conversational, not formal."""


def _build_interviewer_system_prompt(
    product_description: str,
    questions: List[str],
    assumptions: List[str],
    num_turns: int,
) -> str:
    """Build the system prompt for the interviewer agent."""
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
4. If they express skepticism, EXPLORE it — don't try to overcome it. Ask "why do you feel that way?"
5. If they seem positive, STRESS-TEST it — ask "what would make you NOT buy this?" or "what's the biggest risk?"
6. Do NOT ask leading questions. "Would you agree that X is a problem?" is leading. "How do you handle X today?" is not.
7. Do NOT try to sell. You are gathering information, not closing a deal.
8. Ask about specifics: budget, timeline, decision process, current tools, past experiences with similar products.
9. If they say something surprising, follow up on it even if it's off-script.
10. Keep questions to 1-2 sentences. Be conversational.
11. In your final turn, ask a direct closing question: "Based on everything we've discussed, how likely would you be to try something like this?"

Your goal is to understand this person's REAL reaction to the product — positive, negative, or indifferent."""


async def _conduct_interview(
    client,
    persona: Dict,
    config: Dict[str, Any],
    interview_index: int,
) -> Dict:
    """Conduct a single multi-turn interview with one persona."""
    product_description = config["product_description"]
    questions = config.get("questions", [])
    assumptions = config.get("assumptions", [])
    num_turns = config["interview_turns"]
    model = config["llm_model"]

    persona_system = _build_persona_system_prompt(persona, product_description)
    interviewer_system = _build_interviewer_system_prompt(product_description, questions, assumptions, num_turns)

    # Interview state
    interviewer_messages = [{"role": "system", "content": interviewer_system}]
    persona_messages = [{"role": "system", "content": persona_system}]
    transcript = []

    # Generate opening question
    interviewer_messages.append({
        "role": "user",
        "content": f"You are about to interview {persona.get('name', 'a prospect')} who is a {persona.get('title', 'professional')} at a {persona.get('company_type', 'company')} in {persona.get('industry', 'their industry')}. Ask your first question."
    })

    for turn in range(num_turns):
        # Interviewer asks a question
        interviewer_response = await async_chat_completion(
            client=client,
            messages=interviewer_messages,
            model=model,
            temperature=0.7,
            max_tokens=300,
        )

        transcript.append({"role": "interviewer", "turn": turn + 1, "content": interviewer_response})

        # Feed question to persona
        persona_messages.append({"role": "user", "content": interviewer_response})

        # Persona responds
        persona_response = await async_chat_completion(
            client=client,
            messages=persona_messages,
            model=model,
            temperature=0.8,
            max_tokens=400,
        )

        transcript.append({"role": "persona", "turn": turn + 1, "content": persona_response})

        # Feed response back to interviewer for next question
        interviewer_messages.append({"role": "assistant", "content": interviewer_response})
        interviewer_messages.append({"role": "user", "content": f"The prospect responded: \"{persona_response}\"\n\nAsk your next question (turn {turn + 2} of {num_turns})."})

        # Feed response back to persona history
        persona_messages.append({"role": "assistant", "content": persona_response})

    return {
        "persona": persona,
        "transcript": transcript,
        "interview_index": interview_index,
    }


async def run_interviews(
    personas: List[Dict],
    config: Dict[str, Any],
) -> List[Dict]:
    """
    Run all interviews concurrently with rate limiting.

    Args:
        personas: List of persona dicts from the persona engine.
        config: The fully-resolved simulation config dict.

    Returns:
        List of interview result dicts with persona, transcript, and index.
    """
    max_concurrent = config.get("interview_concurrency", 10)
    semaphore = asyncio.Semaphore(max_concurrent)
    client = get_async_client()
    results = [None] * len(personas)

    async def run_one(index: int, persona: Dict):
        async with semaphore:
            try:
                result = await _conduct_interview(client, persona, config, index)
                results[index] = result
                if (index + 1) % 10 == 0 or index == len(personas) - 1:
                    print(f"    Completed interview {index + 1}/{len(personas)}")
            except Exception as e:
                print(f"    [ERROR] Interview {index + 1} failed: {e}")
                results[index] = {
                    "persona": persona,
                    "transcript": [{"role": "error", "turn": 0, "content": str(e)}],
                    "interview_index": index,
                }

    await asyncio.gather(*[run_one(i, p) for i, p in enumerate(personas)])
    await client.close()

    # Filter out None results
    return [r for r in results if r is not None]


def format_transcripts_markdown(interviews: List[Dict]) -> str:
    """Format all interview transcripts as a readable Markdown document."""
    lines = ["# Simulation Interview Transcripts\n"]

    for interview in interviews:
        persona = interview["persona"]
        transcript = interview["transcript"]

        lines.append(f"## Interview #{interview['interview_index'] + 1}: {persona.get('name', 'Unknown')}")
        lines.append(f"**Title:** {persona.get('title', 'N/A')} | **Company:** {persona.get('company_type', 'N/A')} | **Industry:** {persona.get('industry', 'N/A')}")
        lines.append(f"**Archetype:** {persona.get('archetype_name', 'N/A')} | **Disposition:** {persona.get('disposition', 'N/A')} | **Skepticism:** {persona.get('skepticism_score', 'N/A')}/10")
        lines.append("")

        for entry in transcript:
            role_label = "**Interviewer:**" if entry["role"] == "interviewer" else f"**{persona.get('name', 'Prospect')}:**"
            lines.append(f"{role_label} {entry['content']}")
            lines.append("")

        lines.append("---\n")

    return "\n".join(lines)
