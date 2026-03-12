"""
Post-Simulation Chat Engine — Interactive Follow-Up with Personas

After a simulation (interview or focus group) completes, this engine lets
the user "chat" with any persona to probe deeper. The persona retains full
memory of the simulation conversation and responds in character.

Inspired by MiroFish's persistent agent interaction model, adapted for
product-market fit testing and founder customer discovery.

Key features:
  - Persona retains full context from simulation (interview or focus group)
  - User can ask follow-up questions, test pricing, propose alternatives
  - Conversation history persists across multiple exchanges
  - Knowledge graph context available for grounded responses
  - Session serialization for later resumption
"""
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict

from engines.logging_config import get_logger
from engines.llm_client import chat_completion, LLMRetryExhausted, LLMResponseEmpty

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Data Structures
# ──────────────────────────────────────────────

@dataclass
class ChatExchange:
    """A single exchange in a post-simulation chat."""
    user_message: str
    persona_response: str
    turn_number: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChatSession:
    """A complete post-simulation chat session with a persona."""
    persona: Dict
    simulation_type: str  # "interview" or "focus_group"
    simulation_context: str  # The original simulation transcript
    exchanges: List[ChatExchange] = field(default_factory=list)
    graph_context: str = ""
    model: str = "gemini-2.5-flash"

    # Internal state — the full message history for the LLM
    _messages: List[Dict[str, str]] = field(default_factory=list, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "persona": self.persona,
            "simulation_type": self.simulation_type,
            "simulation_context": self.simulation_context,
            "exchanges": [e.to_dict() for e in self.exchanges],
            "graph_context": self.graph_context,
            "model": self.model,
        }

    def save(self, path: str) -> None:
        """Save session to JSON for later resumption."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info("Chat session saved to %s (%d exchanges)", path, len(self.exchanges))


# ──────────────────────────────────────────────
# Session Management
# ──────────────────────────────────────────────

def _build_post_sim_system_prompt(
    persona: Dict,
    simulation_type: str,
    simulation_context: str,
    graph_context: str = "",
) -> str:
    """Build the system prompt for a post-simulation chat persona."""
    graph_block = f"\n## FACTS YOU KNOW ABOUT THE MARKET\n{graph_context}\n" if graph_context else ""

    sim_type_label = "interview" if simulation_type == "interview" else "focus group discussion"

    return f"""You are continuing a conversation after a {sim_type_label} about a product.

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
{graph_block}
## WHAT HAPPENED IN THE {sim_type_label.upper()}
{simulation_context[:4000]}

## POST-SIMULATION CHAT RULES
1. You REMEMBER everything from the {sim_type_label}. Reference specific things you said.
2. Stay COMPLETELY in character. Your opinions haven't magically changed.
3. The person chatting with you now is the FOUNDER/PRODUCT OWNER (not the interviewer).
4. They may propose new ideas, pricing changes, or feature modifications. React authentically:
   - If a new proposal addresses your specific concern, acknowledge it genuinely.
   - If it doesn't address your concern, say so clearly.
   - If it creates new concerns, raise them.
5. You can be MORE candid now than in the formal {sim_type_label} — this is a casual follow-up.
6. If they ask "what would it take to get you to buy?", give a SPECIFIC, honest answer.
7. If you genuinely wouldn't buy at any price, say so and explain why.
8. Keep responses to 3-5 sentences. Be conversational.
9. Reference your SPECIFIC situation — your tools, team, budget, priorities."""


def create_chat_session(
    persona: Dict,
    simulation_transcript: str,
    simulation_type: str = "interview",
    graph_context: str = "",
    model: str = "gemini-2.5-flash",
) -> ChatSession:
    """
    Create a new post-simulation chat session with a persona.

    Args:
        persona: The persona dict from the simulation.
        simulation_transcript: The formatted transcript from the interview or focus group.
        simulation_type: "interview" or "focus_group".
        graph_context: Optional knowledge graph context.
        model: LLM model to use.

    Returns:
        A ChatSession ready for interaction.
    """
    session = ChatSession(
        persona=persona,
        simulation_type=simulation_type,
        simulation_context=simulation_transcript,
        graph_context=graph_context,
        model=model,
    )

    # Initialize the message history with the system prompt
    system_prompt = _build_post_sim_system_prompt(
        persona, simulation_type, simulation_transcript, graph_context,
    )
    session._messages = [{"role": "system", "content": system_prompt}]

    logger.info(
        "Created post-sim chat session with %s (%s)",
        persona.get("name", "Unknown"), simulation_type,
    )

    return session


def create_session_from_interview(
    interview_result: Dict,
    graph_context: str = "",
    model: str = "gemini-2.5-flash",
) -> ChatSession:
    """
    Create a chat session from an interview result dict.

    Args:
        interview_result: The result dict from run_interviews().
        graph_context: Optional knowledge graph context.
        model: LLM model to use.

    Returns:
        A ChatSession ready for interaction.
    """
    persona = interview_result["persona"]
    transcript = interview_result["transcript"]

    # Format the transcript into readable text
    transcript_text = "\n".join(
        f"{'Interviewer' if t['role'] == 'interviewer' else persona.get('name', 'Prospect')}: {t['content']}"
        for t in transcript if t["role"] != "error"
    )

    return create_chat_session(
        persona=persona,
        simulation_transcript=transcript_text,
        simulation_type="interview",
        graph_context=graph_context,
        model=model,
    )


def create_session_from_focus_group(
    focus_group_result: Dict,
    persona_name: str,
    graph_context: str = "",
    model: str = "gemini-2.5-flash",
) -> ChatSession:
    """
    Create a chat session from a focus group result for a specific persona.

    Args:
        focus_group_result: The FocusGroupResult dict.
        persona_name: Name of the persona to chat with.
        graph_context: Optional knowledge graph context.
        model: LLM model to use.

    Returns:
        A ChatSession ready for interaction.
    """
    # Find the persona
    persona = None
    for p in focus_group_result.get("personas", []):
        if p.get("name", "").lower() == persona_name.lower():
            persona = p
            break

    if not persona:
        raise ValueError(f"Persona '{persona_name}' not found in focus group results")

    # Format the focus group transcript
    transcript_entries = focus_group_result.get("transcript", [])
    transcript_text = "\n".join(
        f"{t.get('speaker', 'Unknown')}: {t.get('content', '')}"
        for t in transcript_entries
    )

    return create_chat_session(
        persona=persona,
        simulation_transcript=transcript_text,
        simulation_type="focus_group",
        graph_context=graph_context,
        model=model,
    )


# ──────────────────────────────────────────────
# Chat Interaction
# ──────────────────────────────────────────────

def chat(session: ChatSession, user_message: str) -> str:
    """
    Send a message to the persona and get their response.

    Args:
        session: The active ChatSession.
        user_message: The user's message/question.

    Returns:
        The persona's response string.
    """
    session._messages.append({"role": "user", "content": user_message})

    try:
        response = chat_completion(
            messages=session._messages,
            model=session.model,
            temperature=0.8,
            max_tokens=400,
        )

        session._messages.append({"role": "assistant", "content": response})

        exchange = ChatExchange(
            user_message=user_message,
            persona_response=response,
            turn_number=len(session.exchanges) + 1,
        )
        session.exchanges.append(exchange)

        logger.info(
            "Post-sim chat with %s: turn %d complete",
            session.persona.get("name", "Unknown"), exchange.turn_number,
        )

        return response

    except (LLMRetryExhausted, LLMResponseEmpty) as e:
        logger.error(
            "Post-sim chat failed for %s: %s",
            session.persona.get("name", "Unknown"), str(e)[:200],
        )
        return f"[Chat error: {type(e).__name__}. Please try again.]"

    except Exception as e:
        logger.error(
            "Unexpected error in post-sim chat with %s: %s",
            session.persona.get("name", "Unknown"), str(e)[:200],
        )
        return f"[Unexpected error. Please try again.]"


def chat_batch(session: ChatSession, messages: List[str]) -> List[str]:
    """
    Send multiple messages in sequence and collect responses.

    Useful for scripted follow-up sequences (e.g., testing different pricing).

    Args:
        session: The active ChatSession.
        messages: List of user messages to send in order.

    Returns:
        List of persona responses.
    """
    responses = []
    for msg in messages:
        response = chat(session, msg)
        responses.append(response)
    return responses


def get_session_summary(session: ChatSession) -> str:
    """Generate a summary of the post-simulation chat session."""
    persona = session.persona
    name = persona.get("name", "Unknown")

    lines = [
        f"# Post-Simulation Chat Summary: {name}\n",
        f"**Persona:** {name} — {persona.get('title', 'N/A')} at {persona.get('company_type', 'N/A')}",
        f"**Original Simulation:** {session.simulation_type}",
        f"**Disposition:** {persona.get('disposition', 'N/A')} (Skepticism: {persona.get('skepticism_score', 'N/A')}/10)",
        f"**Follow-up Exchanges:** {len(session.exchanges)}\n",
        "## Conversation\n",
    ]

    for exchange in session.exchanges:
        lines.append(f"**You (Turn {exchange.turn_number}):** {exchange.user_message}\n")
        lines.append(f"**{name}:** {exchange.persona_response}\n")

    return "\n".join(lines)


def load_session(path: str) -> ChatSession:
    """
    Load a previously saved chat session and reconstruct it.

    Note: The internal _messages state is rebuilt from the saved data,
    so the persona will have full context when resumed.
    """
    with open(path) as f:
        data = json.load(f)

    session = ChatSession(
        persona=data["persona"],
        simulation_type=data["simulation_type"],
        simulation_context=data["simulation_context"],
        exchanges=[ChatExchange(**e) for e in data.get("exchanges", [])],
        graph_context=data.get("graph_context", ""),
        model=data.get("model", "gemini-2.5-flash"),
    )

    # Rebuild the message history
    system_prompt = _build_post_sim_system_prompt(
        session.persona, session.simulation_type,
        session.simulation_context, session.graph_context,
    )
    session._messages = [{"role": "system", "content": system_prompt}]

    # Replay previous exchanges
    for exchange in session.exchanges:
        session._messages.append({"role": "user", "content": exchange.user_message})
        session._messages.append({"role": "assistant", "content": exchange.persona_response})

    logger.info(
        "Loaded chat session with %s (%d previous exchanges)",
        session.persona.get("name", "Unknown"), len(session.exchanges),
    )

    return session
