"""
Temporal Multi-Round Sequence Engine — Multi-Touch Sales Simulation

Simulates multi-touch outreach sequences where the agent contacts a prospect
across multiple touchpoints (Day 1 text → Day 3 follow-up → Day 7 offer).
Each touchpoint builds on the previous one — the persona remembers what
happened before and their attitude evolves over time.

Inspired by MiroFish's temporal round system with persistent agent memory,
adapted for sales sequence testing and drip campaign optimization.

Key features:
  - Multi-round sequences with configurable timing/context
  - Persona memory across rounds (remembers previous interactions)
  - Attitude drift modeling (enthusiasm decays, urgency changes)
  - Configurable touchpoint types (SMS, email, phone call)
  - Sequence-level analytics (when do prospects convert? when do they drop off?)
  - Knowledge graph integration for grounded responses
"""
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict

from engines.logging_config import get_logger
from engines.llm_client import chat_completion, LLMRetryExhausted, LLMResponseEmpty
from engines.json_parser import parse_llm_json, JSONParseError

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Data Structures
# ──────────────────────────────────────────────

@dataclass
class Touchpoint:
    """Definition of a single touchpoint in a sequence."""
    round_num: int
    channel: str  # sms, email, phone_call
    timing_label: str  # "Day 1", "Day 3", "Week 2", etc.
    context: str  # What's happening at this point (e.g., "3 days after storm")
    agent_objective: str  # What the agent is trying to achieve this round
    max_turns: int = 3  # Max back-and-forth within this touchpoint

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TouchpointResult:
    """Result of a single touchpoint interaction."""
    round_num: int
    channel: str
    timing_label: str
    transcript: List[Dict[str, str]]  # [{"role": "agent"|"prospect", "content": "..."}]
    outcome: str  # "engaged", "deferred", "declined", "converted", "no_response"
    persona_sentiment: str  # positive, neutral, negative, hostile
    key_objection: str = ""
    next_action: str = ""  # What should happen next

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SequenceResult:
    """Complete results from a multi-touch sequence."""
    persona: Dict
    touchpoints: List[TouchpointResult]
    final_outcome: str  # converted, lost, still_engaged, ghosted
    total_turns: int
    conversion_round: Optional[int] = None  # Which round they converted (if any)
    drop_off_round: Optional[int] = None  # Which round they stopped engaging
    sequence_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "persona": self.persona,
            "touchpoints": [t.to_dict() for t in self.touchpoints],
            "final_outcome": self.final_outcome,
            "total_turns": self.total_turns,
            "conversion_round": self.conversion_round,
            "drop_off_round": self.drop_off_round,
            "sequence_summary": self.sequence_summary,
        }


# ──────────────────────────────────────────────
# Default Sequence Templates
# ──────────────────────────────────────────────

def get_default_sales_sequence() -> List[Touchpoint]:
    """A standard 5-touch outreach sequence."""
    return [
        Touchpoint(
            round_num=1,
            channel="sms",
            timing_label="Day 1",
            context="Initial outreach. First contact with the prospect.",
            agent_objective="Introduce yourself and the service. Get a response.",
            max_turns=3,
        ),
        Touchpoint(
            round_num=2,
            channel="sms",
            timing_label="Day 3",
            context="Follow-up. 2 days since initial contact.",
            agent_objective="Re-engage if no response, or continue conversation if they responded.",
            max_turns=3,
        ),
        Touchpoint(
            round_num=3,
            channel="phone_call",
            timing_label="Day 5",
            context="Phone follow-up. Escalating from text to voice.",
            agent_objective="Have a real conversation. Understand their needs. Propose a specific next step.",
            max_turns=4,
        ),
        Touchpoint(
            round_num=4,
            channel="sms",
            timing_label="Day 10",
            context="Value-add touchpoint. Sharing something useful, not just selling.",
            agent_objective="Provide value (tip, seasonal reminder, free inspection offer). Stay top of mind.",
            max_turns=2,
        ),
        Touchpoint(
            round_num=5,
            channel="sms",
            timing_label="Day 21",
            context="Final follow-up. Last touch before going dormant.",
            agent_objective="Make a clear, time-limited offer. Get a definitive yes or no.",
            max_turns=3,
        ),
    ]


def get_storm_response_sequence() -> List[Touchpoint]:
    """A storm-triggered urgent outreach sequence."""
    return [
        Touchpoint(
            round_num=1,
            channel="sms",
            timing_label="Storm Day",
            context="Major hail/wind event just hit the area. Prospect is a past customer.",
            agent_objective="Check in on them. Offer a free storm damage inspection.",
            max_turns=3,
        ),
        Touchpoint(
            round_num=2,
            channel="phone_call",
            timing_label="Storm +1 Day",
            context="Day after the storm. Insurance adjusters are starting to arrive in the area.",
            agent_objective="Schedule the inspection. Mention insurance process expertise.",
            max_turns=4,
        ),
        Touchpoint(
            round_num=3,
            channel="sms",
            timing_label="Storm +3 Days",
            context="3 days post-storm. Neighbors are getting inspections. Urgency is building.",
            agent_objective="Create urgency. Mention limited crew availability. Confirm or reschedule inspection.",
            max_turns=3,
        ),
        Touchpoint(
            round_num=4,
            channel="sms",
            timing_label="Storm +7 Days",
            context="One week post-storm. Some neighbors already have claims filed.",
            agent_objective="Close. Present the estimate or push for insurance claim filing.",
            max_turns=3,
        ),
    ]


# ──────────────────────────────────────────────
# Prompt Builders
# ──────────────────────────────────────────────

def _build_agent_prompt(
    product_description: str,
    touchpoint: Touchpoint,
    previous_interactions: str,
    persona_summary: str,
    graph_context: str = "",
) -> str:
    """Build the system prompt for the outreach agent at a specific touchpoint."""
    graph_block = f"\n## VERIFIED MARKET DATA\n{graph_context}\n" if graph_context else ""
    prev_block = f"\n## PREVIOUS INTERACTIONS WITH THIS PROSPECT\n{previous_interactions}\n" if previous_interactions else "\nThis is your first contact with this prospect."

    return f"""You are a sales/outreach agent for a company. You are contacting a prospect.

## YOUR COMPANY & SERVICE
{product_description}
{graph_block}
## THIS TOUCHPOINT
Channel: {touchpoint.channel}
Timing: {touchpoint.timing_label}
Context: {touchpoint.context}
Your Objective: {touchpoint.agent_objective}
{prev_block}
## PROSPECT PROFILE
{persona_summary}

## OUTREACH RULES
1. Match the channel: {"Keep messages SHORT (1-3 sentences). This is SMS." if touchpoint.channel == "sms" else "This is a phone call. Be conversational but concise." if touchpoint.channel == "phone_call" else "This is an email. Be professional but personal."}
2. Reference previous interactions if any. Show you remember them.
3. Be helpful, not pushy. Lead with value.
4. If they said no before, acknowledge it and offer something different.
5. If they showed interest before, build on it.
6. Always have a clear call-to-action (schedule inspection, call back, etc.).
7. Use trust signals naturally (years in business, local presence, past work for them).
8. If they're hostile or have clearly said "stop contacting me", respect that and close gracefully."""


def _build_temporal_persona_prompt(
    persona: Dict,
    product_description: str,
    touchpoint: Touchpoint,
    previous_interactions: str,
    attitude_context: str,
    graph_context: str = "",
) -> str:
    """Build the persona prompt with temporal memory and attitude drift."""
    graph_block = f"\n## FACTS YOU KNOW ABOUT THE MARKET\n{graph_context}\n" if graph_context else ""
    prev_block = f"\n## YOUR MEMORY OF PREVIOUS CONTACTS\n{previous_interactions}\n" if previous_interactions else "\nThis is the first time they've contacted you."

    return f"""You are a homeowner/prospect being contacted by a company.

## WHO YOU ARE
Name: {persona.get('name', 'Unknown')}
Title: {persona.get('title', 'Unknown')}
Company/Situation: {persona.get('company_type', 'Unknown')} ({persona.get('company_size', 'Unknown')})
Current tools/services: {persona.get('current_tools', 'Unknown')}
Pain points: {json.dumps(persona.get('pain_points', []))}
Budget sensitivity: {persona.get('budget_sensitivity', 'medium')}
Tech sophistication: {persona.get('tech_sophistication', 'medium')}
Personality: {persona.get('personality_notes', '')}

## YOUR CURRENT DISPOSITION
Base disposition: {persona.get('disposition', 'cautious')}
Skepticism: {persona.get('skepticism_score', 5)}/10

## ATTITUDE EVOLUTION
{attitude_context}
{graph_block}
## THE PRODUCT/SERVICE BEING OFFERED
{product_description}

## CURRENT TOUCHPOINT
Channel: {touchpoint.channel}
Timing: {touchpoint.timing_label}
Context: {touchpoint.context}
{prev_block}
## BEHAVIOR RULES
1. Stay in character. React as this person genuinely would.
2. Your attitude EVOLVES based on previous interactions:
   - If they were helpful before, you're slightly warmer.
   - If they were pushy before, you're more guarded.
   - If a lot of time has passed, you may have forgotten details.
   - If something relevant happened (storm, neighbor got work done), factor that in.
3. Match the channel: {"Reply in short text messages." if touchpoint.channel == "sms" else "Have a phone conversation." if touchpoint.channel == "phone_call" else "Reply to the email."}
4. You can choose NOT to respond (say "[NO RESPONSE]") if you would realistically ignore this message.
5. If you've already said no firmly, don't suddenly become interested unless something genuinely changed.
6. Be specific about your situation — reference your actual tools, budget, timeline.
7. Keep responses to 1-3 sentences for SMS, 3-5 for phone/email."""


# ──────────────────────────────────────────────
# Core Sequence Engine
# ──────────────────────────────────────────────

def _format_previous_interactions(touchpoint_results: List[TouchpointResult]) -> str:
    """Format previous touchpoint results into a readable summary."""
    if not touchpoint_results:
        return ""

    lines = []
    for tp in touchpoint_results:
        lines.append(f"### {tp.timing_label} ({tp.channel})")
        for msg in tp.transcript:
            role_label = "Agent" if msg["role"] == "agent" else "Prospect"
            lines.append(f"- {role_label}: {msg['content']}")
        lines.append(f"Outcome: {tp.outcome}")
        if tp.key_objection:
            lines.append(f"Key objection: {tp.key_objection}")
        lines.append("")

    return "\n".join(lines)


def _compute_attitude_context(
    persona: Dict,
    touchpoint_results: List[TouchpointResult],
    current_touchpoint: Touchpoint,
) -> str:
    """
    Compute how the persona's attitude has evolved based on previous interactions.
    This is the "memory + drift" model.
    """
    if not touchpoint_results:
        return "This is the first contact. Your attitude is at baseline."

    # Analyze the trajectory
    sentiments = [tp.persona_sentiment for tp in touchpoint_results]
    outcomes = [tp.outcome for tp in touchpoint_results]

    positive_count = sentiments.count("positive")
    negative_count = sentiments.count("negative")
    hostile_count = sentiments.count("hostile")
    no_response_count = outcomes.count("no_response")
    declined_count = outcomes.count("declined")

    lines = []

    if hostile_count > 0:
        lines.append("You have been HOSTILE in a previous interaction. You are very unlikely to engage positively unless something dramatically changes.")
    elif declined_count >= 2:
        lines.append("You have declined TWICE already. You are annoyed at being contacted again.")
    elif negative_count > positive_count:
        lines.append("Your overall experience has been negative. You are more guarded than your baseline.")
    elif positive_count > negative_count:
        lines.append("Your overall experience has been positive. You are slightly warmer than your baseline.")
    elif no_response_count >= 2:
        lines.append("You have ignored multiple messages. You are either very busy or not interested.")

    # Time-based drift
    last_outcome = outcomes[-1] if outcomes else "none"
    if last_outcome == "engaged":
        lines.append("Your last interaction was positive — you showed interest.")
    elif last_outcome == "deferred":
        lines.append("You asked to be contacted later. You expect them to remember that.")
    elif last_outcome == "no_response":
        lines.append("You ignored the last message. You may or may not respond this time.")

    return "\n".join(lines) if lines else "Your attitude is at baseline."


def _analyze_touchpoint_outcome(transcript: List[Dict], model: str) -> Dict[str, str]:
    """Use LLM to classify the outcome of a touchpoint."""
    transcript_text = "\n".join(
        f"{'Agent' if m['role'] == 'agent' else 'Prospect'}: {m['content']}"
        for m in transcript
    )

    prompt = f"""Analyze this sales conversation touchpoint and classify the outcome.

Transcript:
{transcript_text}

Return a JSON object:
{{
  "outcome": "engaged|deferred|declined|converted|no_response",
  "sentiment": "positive|neutral|negative|hostile",
  "key_objection": "the main objection raised, or empty string if none",
  "next_action": "what should happen next based on this interaction"
}}

Definitions:
- engaged: Prospect showed interest, asked questions, or agreed to something
- deferred: Prospect said "not now" or "call me later" — not a hard no
- declined: Prospect said no clearly
- converted: Prospect agreed to buy, schedule, or take the desired action
- no_response: Prospect didn't respond or said "[NO RESPONSE]"

Return ONLY the JSON object."""

    try:
        response = chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.2,
            max_tokens=300,
        )
        return parse_llm_json(response, expected_type=dict, context="touchpoint analysis")
    except Exception as e:
        logger.warning("Touchpoint analysis failed: %s", str(e)[:100])
        return {
            "outcome": "engaged",
            "sentiment": "neutral",
            "key_objection": "",
            "next_action": "Continue sequence",
        }


def run_touchpoint(
    persona: Dict,
    touchpoint: Touchpoint,
    product_description: str,
    previous_results: List[TouchpointResult],
    model: str = "gemini-2.5-flash",
    graph_context: str = "",
) -> TouchpointResult:
    """
    Run a single touchpoint interaction.

    Args:
        persona: The persona dict.
        touchpoint: The touchpoint definition.
        product_description: Product/service description.
        previous_results: Results from previous touchpoints in this sequence.
        model: LLM model to use.
        graph_context: Optional knowledge graph context.

    Returns:
        TouchpointResult with transcript and outcome classification.
    """
    previous_interactions = _format_previous_interactions(previous_results)
    attitude_context = _compute_attitude_context(persona, previous_results, touchpoint)

    persona_summary = (
        f"{persona.get('name', 'Unknown')} — {persona.get('title', 'N/A')} at "
        f"{persona.get('company_type', 'N/A')}. Disposition: {persona.get('disposition', 'cautious')}. "
        f"Skepticism: {persona.get('skepticism_score', 5)}/10."
    )

    agent_system = _build_agent_prompt(
        product_description, touchpoint, previous_interactions, persona_summary, graph_context,
    )
    persona_system = _build_temporal_persona_prompt(
        persona, product_description, touchpoint, previous_interactions, attitude_context, graph_context,
    )

    agent_messages = [{"role": "system", "content": agent_system}]
    persona_messages = [{"role": "system", "content": persona_system}]

    transcript = []

    # Agent initiates
    agent_messages.append({
        "role": "user",
        "content": f"Send your {touchpoint.channel} message to the prospect. This is {touchpoint.timing_label}.",
    })

    for turn in range(touchpoint.max_turns):
        # Agent speaks
        try:
            agent_response = chat_completion(
                messages=agent_messages,
                model=model,
                temperature=0.7,
                max_tokens=250,
            )
        except (LLMRetryExhausted, LLMResponseEmpty):
            agent_response = "Hi, just following up on our previous conversation. Do you have a moment?"

        agent_messages.append({"role": "assistant", "content": agent_response})
        transcript.append({"role": "agent", "content": agent_response})

        # Persona responds
        persona_messages.append({
            "role": "user",
            "content": f"The agent sent you this {touchpoint.channel} message:\n\n\"{agent_response}\"\n\nRespond in character. You can say [NO RESPONSE] if you would ignore this.",
        })

        try:
            persona_response = chat_completion(
                messages=persona_messages,
                model=model,
                temperature=0.8,
                max_tokens=250,
            )
        except (LLMRetryExhausted, LLMResponseEmpty):
            persona_response = "[NO RESPONSE]"

        persona_messages.append({"role": "assistant", "content": persona_response})
        transcript.append({"role": "prospect", "content": persona_response})

        # Check for no response — end the touchpoint
        if "[NO RESPONSE]" in persona_response.upper():
            break

        # Feed prospect response back to agent for next turn
        if turn < touchpoint.max_turns - 1:
            agent_messages.append({
                "role": "user",
                "content": f"The prospect responded:\n\n\"{persona_response}\"\n\nContinue the conversation.",
            })

    # Analyze the outcome
    analysis = _analyze_touchpoint_outcome(transcript, model)

    result = TouchpointResult(
        round_num=touchpoint.round_num,
        channel=touchpoint.channel,
        timing_label=touchpoint.timing_label,
        transcript=transcript,
        outcome=analysis.get("outcome", "engaged"),
        persona_sentiment=analysis.get("sentiment", "neutral"),
        key_objection=analysis.get("key_objection", ""),
        next_action=analysis.get("next_action", ""),
    )

    logger.info(
        "Touchpoint %s (%s) with %s: outcome=%s, sentiment=%s",
        touchpoint.timing_label, touchpoint.channel,
        persona.get("name", "Unknown"), result.outcome, result.persona_sentiment,
    )

    return result


def run_sequence(
    persona: Dict,
    touchpoints: List[Touchpoint],
    product_description: str,
    model: str = "gemini-2.5-flash",
    graph_context: str = "",
    stop_on_conversion: bool = True,
    stop_on_hostile: bool = True,
) -> SequenceResult:
    """
    Run a complete multi-touch sequence for a single persona.

    Args:
        persona: The persona dict.
        touchpoints: Ordered list of touchpoint definitions.
        product_description: Product/service description.
        model: LLM model to use.
        graph_context: Optional knowledge graph context.
        stop_on_conversion: Stop the sequence if the prospect converts.
        stop_on_hostile: Stop the sequence if the prospect becomes hostile.

    Returns:
        SequenceResult with all touchpoint results and final outcome.
    """
    logger.info(
        "Starting %d-touch sequence for %s",
        len(touchpoints), persona.get("name", "Unknown"),
    )

    touchpoint_results = []
    conversion_round = None
    drop_off_round = None
    total_turns = 0

    for touchpoint in touchpoints:
        result = run_touchpoint(
            persona=persona,
            touchpoint=touchpoint,
            product_description=product_description,
            previous_results=touchpoint_results,
            model=model,
            graph_context=graph_context,
        )

        touchpoint_results.append(result)
        total_turns += len(result.transcript)

        # Check stopping conditions
        if result.outcome == "converted" and stop_on_conversion:
            conversion_round = touchpoint.round_num
            logger.info("Prospect %s converted at %s!", persona.get("name", "Unknown"), touchpoint.timing_label)
            break

        if result.persona_sentiment == "hostile" and stop_on_hostile:
            drop_off_round = touchpoint.round_num
            logger.info("Prospect %s became hostile at %s. Stopping.", persona.get("name", "Unknown"), touchpoint.timing_label)
            break

        if result.outcome == "declined":
            # Count consecutive declines
            recent_declines = sum(1 for r in touchpoint_results[-2:] if r.outcome == "declined")
            if recent_declines >= 2:
                drop_off_round = touchpoint.round_num
                logger.info("Prospect %s declined twice. Stopping.", persona.get("name", "Unknown"))
                break

    # Determine final outcome
    if conversion_round:
        final_outcome = "converted"
    elif drop_off_round:
        final_outcome = "lost"
    elif all(r.outcome == "no_response" for r in touchpoint_results[-2:]):
        final_outcome = "ghosted"
    elif touchpoint_results and touchpoint_results[-1].outcome in ("engaged", "deferred"):
        final_outcome = "still_engaged"
    else:
        final_outcome = "lost"

    sequence_result = SequenceResult(
        persona=persona,
        touchpoints=touchpoint_results,
        final_outcome=final_outcome,
        total_turns=total_turns,
        conversion_round=conversion_round,
        drop_off_round=drop_off_round,
    )

    logger.info(
        "Sequence complete for %s: %s (conversion: round %s, drop-off: round %s)",
        persona.get("name", "Unknown"), final_outcome, conversion_round, drop_off_round,
    )

    return sequence_result


def run_sequences_batch(
    personas: List[Dict],
    touchpoints: List[Touchpoint],
    product_description: str,
    model: str = "gemini-2.5-flash",
    graph_context: str = "",
) -> List[SequenceResult]:
    """
    Run sequences for multiple personas and collect results.

    Args:
        personas: List of persona dicts.
        touchpoints: Touchpoint sequence to run for each persona.
        product_description: Product/service description.
        model: LLM model to use.
        graph_context: Optional knowledge graph context.

    Returns:
        List of SequenceResult objects.
    """
    results = []
    for idx, persona in enumerate(personas):
        logger.info("Running sequence %d/%d for %s", idx + 1, len(personas), persona.get("name", "Unknown"))
        result = run_sequence(
            persona=persona,
            touchpoints=touchpoints,
            product_description=product_description,
            model=model,
            graph_context=graph_context,
        )
        results.append(result)

    return results


def format_sequence_result(result: SequenceResult) -> str:
    """Format a sequence result as readable Markdown."""
    persona = result.persona
    name = persona.get("name", "Unknown")

    lines = [
        f"# Multi-Touch Sequence: {name}\n",
        f"**Persona:** {name} — {persona.get('title', 'N/A')} at {persona.get('company_type', 'N/A')}",
        f"**Disposition:** {persona.get('disposition', 'N/A')} (Skepticism: {persona.get('skepticism_score', 'N/A')}/10)",
        f"**Final Outcome:** {result.final_outcome.upper()}",
        f"**Total Turns:** {result.total_turns}",
    ]

    if result.conversion_round:
        lines.append(f"**Converted at:** Round {result.conversion_round}")
    if result.drop_off_round:
        lines.append(f"**Dropped off at:** Round {result.drop_off_round}")

    lines.append("")

    for tp in result.touchpoints:
        lines.append(f"## {tp.timing_label} ({tp.channel})\n")
        for msg in tp.transcript:
            role_label = "Agent" if msg["role"] == "agent" else name
            lines.append(f"**{role_label}:** {msg['content']}\n")
        lines.append(f"*Outcome: {tp.outcome} | Sentiment: {tp.persona_sentiment}*")
        if tp.key_objection:
            lines.append(f"*Key objection: {tp.key_objection}*")
        lines.append("")

    if result.sequence_summary:
        lines.append(f"## Sequence Summary\n\n{result.sequence_summary}")

    return "\n".join(lines)


def analyze_sequence_batch(results: List[SequenceResult]) -> Dict[str, Any]:
    """
    Analyze a batch of sequence results for aggregate metrics.

    Returns metrics like conversion rate by round, average drop-off point,
    most common objections, and channel effectiveness.
    """
    total = len(results)
    if total == 0:
        return {"error": "No results to analyze"}

    converted = [r for r in results if r.final_outcome == "converted"]
    lost = [r for r in results if r.final_outcome == "lost"]
    ghosted = [r for r in results if r.final_outcome == "ghosted"]
    still_engaged = [r for r in results if r.final_outcome == "still_engaged"]

    # Conversion by round
    conversion_by_round = {}
    for r in converted:
        rnd = r.conversion_round or 0
        conversion_by_round[rnd] = conversion_by_round.get(rnd, 0) + 1

    # Drop-off by round
    dropoff_by_round = {}
    for r in lost:
        rnd = r.drop_off_round or 0
        dropoff_by_round[rnd] = dropoff_by_round.get(rnd, 0) + 1

    # Objection frequency
    objection_counts = {}
    for r in results:
        for tp in r.touchpoints:
            if tp.key_objection:
                obj = tp.key_objection.lower().strip()
                objection_counts[obj] = objection_counts.get(obj, 0) + 1

    # Channel effectiveness
    channel_outcomes = {}
    for r in results:
        for tp in r.touchpoints:
            ch = tp.channel
            if ch not in channel_outcomes:
                channel_outcomes[ch] = {"engaged": 0, "deferred": 0, "declined": 0, "converted": 0, "no_response": 0}
            outcome = tp.outcome
            if outcome in channel_outcomes[ch]:
                channel_outcomes[ch][outcome] += 1

    return {
        "total_sequences": total,
        "outcomes": {
            "converted": len(converted),
            "lost": len(lost),
            "ghosted": len(ghosted),
            "still_engaged": len(still_engaged),
        },
        "conversion_rate": len(converted) / total if total > 0 else 0,
        "conversion_by_round": conversion_by_round,
        "dropoff_by_round": dropoff_by_round,
        "top_objections": dict(sorted(objection_counts.items(), key=lambda x: x[1], reverse=True)[:10]),
        "channel_effectiveness": channel_outcomes,
        "avg_turns_to_conversion": (
            sum(r.total_turns for r in converted) / len(converted) if converted else 0
        ),
    }
