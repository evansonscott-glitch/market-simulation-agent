"""
Interview Engine — Product-Agnostic (Hardened)

Conducts multi-turn conversational interviews with simulated personas.
Each persona is its own LLM-powered agent that responds in character.
The interviewer adapts its questions based on the persona's responses.

Hardening improvements:
  - Proper structured logging (no print statements)
  - Error boundaries per interview (failed interviews don't crash the run)
  - State persistence via checkpoint (crash recovery)
  - Memory management (stream completed interviews to disk)
  - Graceful degradation (partial results are preserved)
  - Rate-limit-aware concurrency
"""
import asyncio
import json
from typing import List, Dict, Any, Optional, Set

from engines.logging_config import get_logger
from engines.llm_client import (
    get_async_client, async_chat_completion,
    LLMRetryExhausted, LLMResponseEmpty,
)
from engines.checkpoint import SimulationCheckpoint

logger = get_logger(__name__)


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
    """
    Conduct a single multi-turn interview with one persona.

    Error handling: if a single turn fails, we capture what we have
    and return a partial interview rather than losing everything.
    """
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
    completed_turns = 0

    # Generate opening context for interviewer
    interviewer_messages.append({
        "role": "user",
        "content": (
            f"You are about to interview {persona.get('name', 'a prospect')} who is a "
            f"{persona.get('title', 'professional')} at a {persona.get('company_type', 'company')} "
            f"in {persona.get('industry', 'their industry')}. Ask your first question."
        ),
    })

    for turn in range(num_turns):
        try:
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
            interviewer_messages.append({
                "role": "user",
                "content": (
                    f'The prospect responded: "{persona_response}"\n\n'
                    f"Ask your next question (turn {turn + 2} of {num_turns})."
                ),
            })

            # Feed response back to persona history
            persona_messages.append({"role": "assistant", "content": persona_response})
            completed_turns += 1

        except (LLMRetryExhausted, LLMResponseEmpty) as e:
            logger.warning(
                "Interview %d turn %d failed for %s: %s. Saving partial transcript.",
                interview_index + 1, turn + 1, persona.get("name", "unknown"), str(e)[:100],
            )
            transcript.append({
                "role": "error",
                "turn": turn + 1,
                "content": f"Turn failed: {type(e).__name__}",
            })
            break  # Save what we have

        except Exception as e:
            logger.error(
                "Unexpected error in interview %d turn %d: %s",
                interview_index + 1, turn + 1, str(e)[:100],
            )
            transcript.append({
                "role": "error",
                "turn": turn + 1,
                "content": f"Turn failed: {type(e).__name__}",
            })
            break

    return {
        "persona": persona,
        "transcript": transcript,
        "interview_index": interview_index,
        "completed_turns": completed_turns,
        "total_turns": num_turns,
        "partial": completed_turns < num_turns,
    }


async def run_interviews(
    personas: List[Dict],
    config: Dict[str, Any],
    checkpoint: Optional[SimulationCheckpoint] = None,
) -> List[Dict]:
    """
    Run all interviews concurrently with rate limiting and checkpointing.

    Features:
      - Crash recovery: skips already-completed interviews from checkpoint
      - Memory management: saves each interview to disk immediately
      - Graceful degradation: failed interviews are recorded, not fatal
      - Progress logging at regular intervals

    Args:
        personas: List of persona dicts from the persona engine.
        config: The fully-resolved simulation config dict.
        checkpoint: Optional checkpoint manager for persistence.

    Returns:
        List of interview result dicts with persona, transcript, and index.
    """
    max_concurrent = config.get("interview_concurrency", 10)
    semaphore = asyncio.Semaphore(max_concurrent)
    client = get_async_client()

    total = len(personas)
    results: List[Optional[Dict]] = [None] * total
    completed_count = 0
    failed_count = 0
    skipped_count = 0

    # Check for existing checkpoint data
    already_completed: Set[int] = set()
    if checkpoint:
        already_completed = checkpoint.get_completed_interview_indices()
        if already_completed:
            logger.info(
                "Resuming from checkpoint: %d/%d interviews already completed",
                len(already_completed), total,
            )
            # Load already-completed interviews
            for idx in already_completed:
                interview = checkpoint.load_interview(idx)
                if interview and idx < total:
                    results[idx] = interview
                    completed_count += 1
                    skipped_count += 1

    async def run_one(index: int, persona: Dict):
        nonlocal completed_count, failed_count

        # Skip if already completed in checkpoint
        if index in already_completed:
            return

        async with semaphore:
            try:
                result = await _conduct_interview(client, persona, config, index)
                results[index] = result

                # Save to checkpoint immediately (memory management + crash recovery)
                if checkpoint:
                    checkpoint.save_interview(index, result)

                completed_count += 1

                # Progress logging (every 10 interviews or at the end)
                if completed_count % 10 == 0 or completed_count == total:
                    logger.info(
                        "Interview progress: %d/%d completed (%d failed, %d skipped)",
                        completed_count, total, failed_count, skipped_count,
                    )
                    if checkpoint:
                        checkpoint.save_state(
                            phase="interviews",
                            progress=f"{completed_count}/{total} interviews",
                            metadata={"failed": failed_count, "skipped": skipped_count},
                        )

            except Exception as e:
                failed_count += 1
                logger.error(
                    "Interview %d failed for %s: %s",
                    index + 1, persona.get("name", "unknown"), str(e)[:100],
                )
                # Save a failure record so we know this one was attempted
                error_result = {
                    "persona": persona,
                    "transcript": [{"role": "error", "turn": 0, "content": str(e)[:200]}],
                    "interview_index": index,
                    "completed_turns": 0,
                    "total_turns": config["interview_turns"],
                    "partial": True,
                    "error": True,
                }
                results[index] = error_result
                if checkpoint:
                    checkpoint.save_interview(index, error_result)

    # Run all interviews concurrently
    await asyncio.gather(*[run_one(i, p) for i, p in enumerate(personas)])

    # Cleanup
    try:
        await client.close()
    except Exception:
        pass

    # Filter out None results and log summary
    valid_results = [r for r in results if r is not None]
    partial_count = sum(1 for r in valid_results if r.get("partial", False))

    logger.info(
        "Interviews complete: %d/%d successful, %d partial, %d failed",
        len(valid_results) - partial_count, total, partial_count, failed_count,
    )

    if checkpoint:
        checkpoint.save_state(
            phase="interviews_complete",
            progress=f"{len(valid_results)}/{total} interviews completed",
            metadata={
                "total": total,
                "completed": len(valid_results),
                "partial": partial_count,
                "failed": failed_count,
                "skipped_from_checkpoint": skipped_count,
            },
        )

    return valid_results


def format_transcripts_markdown(interviews: List[Dict]) -> str:
    """Format all interview transcripts as a readable Markdown document."""
    lines = ["# Simulation Interview Transcripts\n"]

    for interview in interviews:
        persona = interview["persona"]
        transcript = interview["transcript"]

        lines.append(f"## Interview #{interview['interview_index'] + 1}: {persona.get('name', 'Unknown')}")
        lines.append(
            f"**Title:** {persona.get('title', 'N/A')} | "
            f"**Company:** {persona.get('company_type', 'N/A')} | "
            f"**Industry:** {persona.get('industry', 'N/A')}"
        )
        lines.append(
            f"**Archetype:** {persona.get('archetype_name', 'N/A')} | "
            f"**Disposition:** {persona.get('disposition', 'N/A')} | "
            f"**Skepticism:** {persona.get('skepticism_score', 'N/A')}/10"
        )

        if interview.get("partial"):
            lines.append(
                f"**Note:** Partial interview ({interview.get('completed_turns', '?')}"
                f"/{interview.get('total_turns', '?')} turns completed)"
            )
        lines.append("")

        for entry in transcript:
            if entry["role"] == "error":
                lines.append(f"*[Turn {entry['turn']} failed: {entry['content']}]*")
            elif entry["role"] == "interviewer":
                lines.append(f"**Interviewer:** {entry['content']}")
            else:
                lines.append(f"**{persona.get('name', 'Prospect')}:** {entry['content']}")
            lines.append("")

        lines.append("---\n")

    return "\n".join(lines)
