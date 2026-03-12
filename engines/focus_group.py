"""
Focus Group Engine — Agent-to-Agent Interaction

Simulates a moderated focus group discussion where multiple personas
interact with each other (not just with an interviewer). This surfaces
emergent group dynamics: social proof, herd behavior, contrarian pushback,
opinion cascades, and peer influence.

Inspired by MiroFish's agent-to-agent social simulation, adapted for
product-market fit testing and sales conversation simulation.

Key features:
  - Moderated round-robin discussion with a facilitator agent
  - Personas react to EACH OTHER's comments, not just the facilitator
  - Group dynamics tracking (who influenced whom, opinion shifts)
  - Configurable group size (3-8 personas per group)
  - Knowledge graph integration for grounded responses
"""
import asyncio
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict

from engines.logging_config import get_logger
from engines.llm_client import (
    get_async_client, async_chat_completion,
    LLMRetryExhausted, LLMResponseEmpty,
)

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Data Structures
# ──────────────────────────────────────────────

@dataclass
class FocusGroupTurn:
    """A single turn in the focus group discussion."""
    round_num: int
    speaker: str  # persona name or "facilitator"
    speaker_role: str  # "facilitator" or "participant"
    content: str
    reacting_to: Optional[str] = None  # name of persona they're responding to
    sentiment: Optional[str] = None  # positive, negative, neutral, mixed

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OpinionShift:
    """Tracks when a persona changes their stance during the discussion."""
    persona_name: str
    from_stance: str
    to_stance: str
    trigger: str  # what caused the shift
    round_num: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FocusGroupResult:
    """Complete results from a focus group session."""
    group_id: int
    personas: List[Dict]
    transcript: List[FocusGroupTurn]
    opinion_shifts: List[OpinionShift]
    num_rounds: int
    group_dynamics_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "personas": self.personas,
            "transcript": [t.to_dict() for t in self.transcript],
            "opinion_shifts": [o.to_dict() for o in self.opinion_shifts],
            "num_rounds": self.num_rounds,
            "group_dynamics_summary": self.group_dynamics_summary,
        }


# ──────────────────────────────────────────────
# Prompt Builders
# ──────────────────────────────────────────────

def _build_facilitator_prompt(
    product_description: str,
    questions: List[str],
    assumptions: List[str],
    participant_profiles: str,
    num_rounds: int,
    graph_context: str = "",
) -> str:
    """Build the system prompt for the focus group facilitator."""
    items = []
    if assumptions:
        items.append("## ASSUMPTIONS TO VALIDATE\n" + "\n".join(f"- {a}" for a in assumptions))
    if questions:
        items.append("## QUESTIONS TO EXPLORE\n" + "\n".join(f"- {q}" for q in questions))
    exploration = "\n\n".join(items) if items else "Explore the group's reactions to the product."

    graph_block = f"\n## VERIFIED MARKET DATA\n{graph_context}\n" if graph_context else ""

    return f"""You are a skilled focus group facilitator conducting a moderated discussion about a product.

## THE PRODUCT
{product_description}
{graph_block}
{exploration}

## PARTICIPANTS
{participant_profiles}

## FACILITATION RULES
1. You are moderating a group of {num_rounds} discussion rounds.
2. Start with a broad, open-ended question to the group.
3. After participants respond, pick up on the MOST INTERESTING thread — especially disagreements.
4. Actively encourage participants to react to EACH OTHER's comments:
   - "Interesting point, [Name]. [Other Name], what do you think about that?"
   - "[Name] just said X. Does anyone see it differently?"
   - "I notice [Name] and [Name] disagree on this. Let's explore that."
5. If the group is too agreeable, play devil's advocate or introduce a challenging scenario.
6. If someone is quiet, draw them in: "[Name], you haven't weighed in on this yet."
7. Do NOT lecture or provide information. Your job is to facilitate THEIR discussion.
8. Keep your prompts short (1-3 sentences). Let the participants do the talking.
9. In the final round, ask each participant for their bottom-line verdict.
10. Address specific participants by name when you want them to respond."""


def _build_focus_group_persona_prompt(
    persona: Dict,
    product_description: str,
    other_participants: str,
    graph_context: str = "",
) -> str:
    """Build the system prompt for a persona in a focus group setting."""
    graph_block = f"\n## FACTS YOU KNOW ABOUT THE MARKET\n{graph_context}\n" if graph_context else ""

    return f"""You are participating in a focus group discussion about a product.

## WHO YOU ARE
Name: {persona.get('name', 'Unknown')}
Title: {persona.get('title', 'Unknown')}
Company: {persona.get('company_type', 'Unknown')} ({persona.get('company_size', 'Unknown')})
Industry: {persona.get('industry', 'Unknown')}
Experience: {persona.get('years_experience', 'Unknown')} years
Current tools: {persona.get('current_tools', 'Unknown')}
Pain points: {json.dumps(persona.get('pain_points', []))}
Priorities: {json.dumps(persona.get('priorities', []))}
Budget sensitivity: {persona.get('budget_sensitivity', 'medium')}
Tech sophistication: {persona.get('tech_sophistication', 'medium')}
Personality: {persona.get('personality_notes', '')}

## YOUR DISPOSITION
You are {persona.get('disposition', 'cautious')} about new products.
Your skepticism level is {persona.get('skepticism_score', 5)}/10.

## THE PRODUCT BEING DISCUSSED
{product_description}
{graph_block}
## OTHER PARTICIPANTS IN THE GROUP
{other_participants}

## FOCUS GROUP BEHAVIOR RULES
1. Stay COMPLETELY in character. Respond as this person would.
2. You are in a GROUP discussion. React to what OTHER participants say, not just the facilitator.
3. If someone says something you agree with, build on it: "Yeah, exactly what [Name] said..."
4. If someone says something you disagree with, push back: "I see it differently than [Name]..."
5. If someone shares an experience that resonates, share your own related experience.
6. If someone is being naive or overly optimistic, call it out (politely or bluntly, depending on your personality).
7. Your disposition is {persona.get('disposition', 'cautious')}:
   - "enthusiastic": You're excited but still have practical questions. You might influence others positively.
   - "open": You're willing to listen. You might be swayed by good arguments from peers.
   - "cautious": You're careful. Peer pressure won't move you, but solid evidence from peers might.
   - "skeptical": You push back. You might make others doubt their enthusiasm.
   - "resistant": You're the contrarian. You challenge the group consensus.
8. Keep responses to 2-4 sentences. Be conversational and natural.
9. Use the other participants' names when responding to them.
10. If the facilitator asks you directly, you MUST respond."""


# ──────────────────────────────────────────────
# Core Focus Group Engine
# ──────────────────────────────────────────────

async def _run_focus_group_round(
    client,
    facilitator_messages: List[Dict],
    persona_message_histories: Dict[str, List[Dict]],
    personas: List[Dict],
    round_num: int,
    num_rounds: int,
    model: str,
    transcript: List[FocusGroupTurn],
) -> None:
    """
    Run a single round of the focus group discussion.

    Flow:
    1. Facilitator poses a question/prompt to the group
    2. Each persona responds (in a randomized order to avoid position bias)
    3. Responses are shared with all participants for the next round
    """
    import random

    # Step 1: Facilitator speaks
    if round_num == 1:
        facilitator_messages.append({
            "role": "user",
            "content": "The focus group is starting. Ask your opening question to the group.",
        })
    else:
        # Build a summary of last round's discussion for the facilitator
        last_round_comments = [t for t in transcript if t.round_num == round_num - 1 and t.speaker_role == "participant"]
        discussion_summary = "\n".join(
            f"- {t.speaker}: \"{t.content}\"" for t in last_round_comments
        )
        closing_instruction = (
            "Ask your final wrap-up question -- get each person's bottom-line verdict."
            if round_num == num_rounds
            else "Guide the discussion forward. Pick up on the most interesting thread, especially any disagreements."
        )
        facilitator_messages.append({
            "role": "user",
            "content": (
                f"Here's what the participants said in the last round:\n\n{discussion_summary}\n\n"
                f"This is round {round_num} of {num_rounds}. "
                f"{closing_instruction}"
            ),
        })

    try:
        facilitator_response = await async_chat_completion(
            client=client,
            messages=facilitator_messages,
            model=model,
            temperature=0.7,
            max_tokens=300,
        )
    except (LLMRetryExhausted, LLMResponseEmpty) as e:
        logger.error("Facilitator failed in round %d: %s", round_num, str(e)[:100])
        facilitator_response = f"Let's continue our discussion. What are your thoughts? (Round {round_num})"

    facilitator_messages.append({"role": "assistant", "content": facilitator_response})
    transcript.append(FocusGroupTurn(
        round_num=round_num,
        speaker="Facilitator",
        speaker_role="facilitator",
        content=facilitator_response,
    ))

    # Step 2: Each persona responds (randomized order)
    persona_order = list(range(len(personas)))
    random.shuffle(persona_order)

    round_responses = []

    for idx in persona_order:
        persona = personas[idx]
        name = persona.get("name", f"Participant {idx + 1}")
        history = persona_message_histories[name]

        # Build the context: facilitator question + previous responses this round
        context_parts = [f"Facilitator: \"{facilitator_response}\""]
        for prev_resp in round_responses:
            context_parts.append(f"{prev_resp['name']}: \"{prev_resp['content']}\"")

        round_context = "\n".join(context_parts)

        history.append({
            "role": "user",
            "content": (
                f"Round {round_num} of the focus group discussion:\n\n{round_context}\n\n"
                f"Respond to the discussion. React to what others have said if relevant."
            ),
        })

        try:
            persona_response = await async_chat_completion(
                client=client,
                messages=history,
                model=model,
                temperature=0.8,
                max_tokens=300,
            )
        except (LLMRetryExhausted, LLMResponseEmpty) as e:
            logger.warning("Persona %s failed in round %d: %s", name, round_num, str(e)[:100])
            persona_response = f"I'd need to think more about that."

        history.append({"role": "assistant", "content": persona_response})

        # Determine who they're reacting to (simple heuristic)
        reacting_to = None
        for prev in round_responses:
            if prev["name"].lower() in persona_response.lower():
                reacting_to = prev["name"]
                break

        transcript.append(FocusGroupTurn(
            round_num=round_num,
            speaker=name,
            speaker_role="participant",
            content=persona_response,
            reacting_to=reacting_to,
        ))

        round_responses.append({"name": name, "content": persona_response})

    logger.info("Focus group round %d/%d complete (%d responses)", round_num, num_rounds, len(round_responses))


async def _analyze_group_dynamics(
    transcript: List[FocusGroupTurn],
    personas: List[Dict],
    product_description: str,
    model: str,
) -> tuple:
    """Analyze the focus group transcript for opinion shifts and dynamics."""
    transcript_text = "\n".join(
        f"[Round {t.round_num}] {t.speaker}: {t.content}" for t in transcript
    )

    system_prompt = """You are an expert focus group analyst. Analyze this transcript and identify:

1. OPINION SHIFTS: Did any participant change their stance during the discussion? Who influenced them?
2. GROUP DYNAMICS: Was there a dominant voice? Did social proof occur? Any contrarian effects?
3. KEY INSIGHTS: What did the group discussion reveal that individual interviews would miss?

Return a JSON object:
{
  "opinion_shifts": [
    {"persona_name": "...", "from_stance": "...", "to_stance": "...", "trigger": "what caused it", "round_num": N}
  ],
  "dynamics_summary": "2-3 paragraph analysis of the group dynamics",
  "emergent_insights": ["insight 1", "insight 2"]
}

Return ONLY the JSON object."""

    client = get_async_client()
    try:
        response = await async_chat_completion(
            client=client,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Product: {product_description}\n\nTranscript:\n{transcript_text[:6000]}"},
            ],
            model=model,
            temperature=0.3,
            max_tokens=2000,
        )
        await client.close()

        from engines.json_parser import parse_llm_json
        analysis = parse_llm_json(response, expected_type=dict, context="focus group analysis")

        shifts = []
        for s in analysis.get("opinion_shifts", []):
            if isinstance(s, dict):
                shifts.append(OpinionShift(
                    persona_name=s.get("persona_name", "Unknown"),
                    from_stance=s.get("from_stance", "unknown"),
                    to_stance=s.get("to_stance", "unknown"),
                    trigger=s.get("trigger", "unknown"),
                    round_num=s.get("round_num", 0),
                ))

        summary = analysis.get("dynamics_summary", "No dynamics analysis available.")
        return shifts, summary

    except Exception as e:
        logger.error("Focus group analysis failed: %s", str(e)[:200])
        try:
            await client.close()
        except Exception:
            pass
        return [], "Analysis failed."


async def run_focus_group(
    personas: List[Dict],
    config: Dict[str, Any],
    group_id: int = 1,
    graph_context: str = "",
) -> FocusGroupResult:
    """
    Run a single focus group session with the given personas.

    Args:
        personas: List of 3-8 persona dicts (from persona engine).
        config: Simulation config dict.
        group_id: Identifier for this group.
        graph_context: Optional knowledge graph context string.

    Returns:
        FocusGroupResult with full transcript and analysis.
    """
    product_description = config["product_description"]
    questions = config.get("questions", [])
    assumptions = config.get("assumptions", [])
    num_rounds = config.get("focus_group_rounds", 4)
    model = config.get("llm_model", "gemini-2.5-flash")

    # Build participant profiles summary
    participant_profiles = "\n".join(
        f"- {p.get('name', 'Unknown')}: {p.get('title', 'N/A')} at {p.get('company_type', 'N/A')} "
        f"({p.get('disposition', 'cautious')}, skepticism {p.get('skepticism_score', 5)}/10)"
        for p in personas
    )

    other_participants_text = "\n".join(
        f"- {p.get('name', 'Unknown')}: {p.get('title', 'N/A')} at {p.get('company_type', 'N/A')}"
        for p in personas
    )

    # Initialize facilitator
    facilitator_system = _build_facilitator_prompt(
        product_description, questions, assumptions,
        participant_profiles, num_rounds, graph_context,
    )
    facilitator_messages = [{"role": "system", "content": facilitator_system}]

    # Initialize each persona
    persona_message_histories = {}
    for persona in personas:
        name = persona.get("name", "Unknown")
        persona_system = _build_focus_group_persona_prompt(
            persona, product_description, other_participants_text, graph_context,
        )
        persona_message_histories[name] = [{"role": "system", "content": persona_system}]

    # Run the discussion
    client = get_async_client()
    transcript: List[FocusGroupTurn] = []

    logger.info("Starting focus group #%d with %d participants, %d rounds", group_id, len(personas), num_rounds)

    for round_num in range(1, num_rounds + 1):
        await _run_focus_group_round(
            client=client,
            facilitator_messages=facilitator_messages,
            persona_message_histories=persona_message_histories,
            personas=personas,
            round_num=round_num,
            num_rounds=num_rounds,
            model=model,
            transcript=transcript,
        )

    try:
        await client.close()
    except Exception:
        pass

    # Analyze group dynamics
    opinion_shifts, dynamics_summary = await _analyze_group_dynamics(
        transcript, personas, product_description, model,
    )

    result = FocusGroupResult(
        group_id=group_id,
        personas=personas,
        transcript=transcript,
        opinion_shifts=opinion_shifts,
        num_rounds=num_rounds,
        group_dynamics_summary=dynamics_summary,
    )

    logger.info(
        "Focus group #%d complete: %d turns, %d opinion shifts detected",
        group_id, len(transcript), len(opinion_shifts),
    )

    return result


async def run_multiple_focus_groups(
    all_personas: List[Dict],
    config: Dict[str, Any],
    group_size: int = 5,
    graph_context: str = "",
) -> List[FocusGroupResult]:
    """
    Split personas into groups and run multiple focus group sessions.

    Args:
        all_personas: Full list of personas.
        config: Simulation config.
        group_size: Number of personas per group (3-8 recommended).
        graph_context: Optional knowledge graph context.

    Returns:
        List of FocusGroupResult objects.
    """
    import random

    # Shuffle to mix archetypes across groups
    shuffled = list(all_personas)
    random.shuffle(shuffled)

    # Split into groups
    groups = []
    for i in range(0, len(shuffled), group_size):
        group = shuffled[i:i + group_size]
        if len(group) >= 3:  # Minimum 3 for a meaningful group discussion
            groups.append(group)

    logger.info("Running %d focus groups (%d personas, group size %d)", len(groups), len(all_personas), group_size)

    results = []
    for idx, group in enumerate(groups):
        result = await run_focus_group(
            personas=group,
            config=config,
            group_id=idx + 1,
            graph_context=graph_context,
        )
        results.append(result)

    return results


def format_focus_group_transcript(result: FocusGroupResult) -> str:
    """Format a focus group result as readable Markdown."""
    lines = [f"# Focus Group #{result.group_id} Transcript\n"]

    # Participant list
    lines.append("## Participants")
    for p in result.personas:
        lines.append(
            f"- **{p.get('name', 'Unknown')}**: {p.get('title', 'N/A')} at {p.get('company_type', 'N/A')} "
            f"(Disposition: {p.get('disposition', 'N/A')}, Skepticism: {p.get('skepticism_score', 'N/A')}/10)"
        )
    lines.append("")

    # Transcript by round
    current_round = 0
    for turn in result.transcript:
        if turn.round_num != current_round:
            current_round = turn.round_num
            lines.append(f"\n## Round {current_round}\n")

        if turn.speaker_role == "facilitator":
            lines.append(f"**Facilitator:** {turn.content}\n")
        else:
            reaction = f" *(reacting to {turn.reacting_to})*" if turn.reacting_to else ""
            lines.append(f"**{turn.speaker}:**{reaction} {turn.content}\n")

    # Opinion shifts
    if result.opinion_shifts:
        lines.append("\n## Opinion Shifts Detected\n")
        for shift in result.opinion_shifts:
            lines.append(
                f"- **{shift.persona_name}** shifted from *{shift.from_stance}* to *{shift.to_stance}* "
                f"in round {shift.round_num} — triggered by: {shift.trigger}"
            )

    # Dynamics summary
    if result.group_dynamics_summary:
        lines.append(f"\n## Group Dynamics Analysis\n\n{result.group_dynamics_summary}")

    return "\n".join(lines)
