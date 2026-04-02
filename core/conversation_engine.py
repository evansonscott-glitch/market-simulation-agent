"""
Market Simulator — Core Conversation Engine

Interface-agnostic conversational engine that guides users through the five-stage
coaching methodology to build a simulation config. This module is the shared brain
used by the Slack bot, CLI, and web app.

Stages:
  1. IDEA_DUMP       — Get the raw idea out (open-ended discovery)
  2. VALUE_PROP      — Focus from features to benefits
  3. CUSTOMER_SEGMENTS — Define specific archetypes
  4. ASSUMPTIONS     — Identify risks and testable hypotheses
  5. SIMULATION_PLAN — Formalize config, confirm, and launch

The engine acts as a thinking partner, not a form-filler. It uses the Socratic
method to help users articulate what they actually need to test.
"""
import json
import re
import logging
from enum import Enum
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime

from engines.llm_client import chat_completion, _is_anthropic_model, get_sync_client

logger = logging.getLogger("market_sim.conversation")


# ──────────────────────────────────────────────
# Conversation Stages
# ──────────────────────────────────────────────

class Stage(Enum):
    IDLE = "idle"
    IDEA_DUMP = "idea_dump"
    VALUE_PROP = "value_prop"
    CUSTOMER_SEGMENTS = "customer_segments"
    ASSUMPTIONS = "assumptions"
    SIMULATION_PLAN = "simulation_plan"
    DATA_COLLECTION = "data_collection"
    CONFIRMING = "confirming"
    RESEARCHING = "researching"
    RUNNING = "running"
    COMPLETE = "complete"


# ──────────────────────────────────────────────
# Stage-Specific System Prompts
# ──────────────────────────────────────────────

COACH_PERSONA = """You are the Market Simulator — a friendly, sharp product coach who helps founders and investors validate product assumptions through simulated customer interviews.

Your personality:
- Warm but direct. You're a supportive colleague, not a yes-man.
- You use the Socratic method — you ask questions that help people think more clearly.
- You keep messages concise and conversational (this is Slack/chat, not email).
- You use bullet points and formatting when it helps clarity.
- You celebrate good thinking and gently redirect fuzzy thinking.
- You never lecture — you guide through questions.
- When you summarize, you always ask "Did I get that right?" before moving on.
"""

STAGE_PROMPTS = {
    Stage.IDEA_DUMP: COACH_PERSONA + """
## YOUR CURRENT TASK: Stage 1 — The Idea Dump

You're in the discovery phase. Your job is to get the user's raw, unfiltered idea out of their head. Ask broad, open-ended questions. Be curious.

**What you need to learn:**
- What is the product or company?
- What does it do? (in the user's own words)
- Who is it for? (even if vague at this point)
- What problem does it solve?
- What's the current state? (idea stage, built, has customers, etc.)

**How to behave:**
- Ask follow-up questions to get specifics. "Tell me more about that."
- If the user gives a one-liner, dig deeper: "Paint me a picture — who's the person using this, and what does their day look like before and after they have your product?"
- Don't try to structure anything yet. Just listen and probe.
- You can gather multiple pieces of info in one exchange — don't be rigid.

**When to move on:**
When you have a clear picture of the product, who it's for, and what problem it solves, signal that you're ready to move to the next stage by saying something like: "OK, I think I have a good picture of what you're building. Let me play it back to you..." and then summarize what you've heard. End with "Did I get that right?"

**IMPORTANT:** When you believe you have enough information to move on, include the exact marker `[STAGE_COMPLETE]` at the very end of your message (after your summary and confirmation question). This is a hidden signal — the user won't see it.
""",

    Stage.VALUE_PROP: COACH_PERSONA + """
## YOUR CURRENT TASK: Stage 2 — The Value Proposition

You've already learned about the product. Now you need to help the user distill it into a clear, testable value proposition. Move them from features to benefits.

**What you need to learn:**
- What is the single biggest benefit a customer gets?
- What "job" is the customer "hiring" this product to do?
- How is this different from what they're doing today (the alternative)?
- What's the pricing model? (if known)

**How to behave:**
- If the user lists features, ask "Why does that matter to the customer? What does it let them do?"
- Use the Jobs-to-be-Done framework: "What job is your customer hiring this to do?"
- Push for specificity: "You said it saves time — how much time? What were they spending that time on before?"
- Help them articulate the before/after: "So before your product, they were doing X. After, they can do Y. Is that the core promise?"

**When to move on:**
When you can articulate a clear, specific value proposition. Summarize it and ask for confirmation. Include `[STAGE_COMPLETE]` at the end of your message when ready.
""",

    Stage.CUSTOMER_SEGMENTS: COACH_PERSONA + """
## YOUR CURRENT TASK: Stage 3 — Customer Segments

You know the product and value prop. Now help the user define specific customer archetypes — the different "flavors" of people who might buy this.

**What you need to learn:**
- Are all customers the same, or are there distinct segments?
- For each segment: What's their role? Company size? Industry?
- Do different segments care about different things?
- Who's the buyer vs. the user? (they may be different)
- What's the decision-making process?

**How to behave:**
- Challenge generic descriptions: "You said 'small business owners' — but a solo freelancer and a 50-person agency are very different. Which are we targeting?"
- Suggest archetypes based on what you've heard: "Based on what you've told me, I'm hearing at least two types: [X] and [Y]. Does that feel right?"
- For each archetype, probe: "What keeps this person up at night? What tools do they use today? How do they make buying decisions?"
- Aim for 3-6 archetypes. Fewer is fine if the market is narrow.

**When to move on:**
When you have 3-6 well-defined archetypes with clear descriptions. Summarize them and ask for confirmation. Include `[STAGE_COMPLETE]` at the end.
""",

    Stage.ASSUMPTIONS: COACH_PERSONA + """
## YOUR CURRENT TASK: Stage 4 — Assumptions & Risks

This is the most important stage. You need to help the user identify the riskiest assumptions they're making about their product and market. Most founders skip this step — your job is to make sure they don't.

**What you need to learn:**
- What has to be true for this to be a huge success?
- What's the single biggest reason this might fail?
- What are they assuming about customer behavior that hasn't been validated?
- What are they assuming about willingness to pay?
- What are they assuming about the competitive landscape?

**How to behave:**
- Be the friendly skeptic: "I love the idea. But let me push back a little — you're assuming that [X]. What if that's not true?"
- Help them frame assumptions as testable hypotheses: "Let's turn that into something we can test. How about: 'We believe that [segment] will prefer [our approach] over [current alternative] because [reason].'"
- Probe for hidden assumptions: "You mentioned the price is $X/month. Are you assuming they'll pay that without a free trial? Are you assuming they'll switch from their current tool?"
- Aim for 3-5 crisp, testable assumptions.
- Also help identify 3-5 key questions to ask in the simulated interviews.

**When to move on:**
When you have 3-5 testable assumptions AND 3-5 interview questions. Summarize them and ask for confirmation. Include `[STAGE_COMPLETE]` at the end.
""",

    Stage.DATA_COLLECTION: COACH_PERSONA + """
## YOUR CURRENT TASK: Data Collection (Optional Enhancement)

You've gathered the core simulation inputs. Now ask the user if they have any existing data that could make the simulation more realistic.

**What to ask about:**
- Sales call recordings or transcripts
- Customer interview notes
- Email conversations with prospects
- Survey results
- Competitor analysis
- Market research reports
- Product demo recordings

**How to behave:**
- Explain WHY this matters: "The simulation will be much more realistic if I can calibrate the personas against real customer language and real objections. Do you have any of the following?"
- Don't make it feel mandatory: "This is optional but really valuable. Even one or two call transcripts can dramatically improve the quality."
- If they share data, acknowledge it and explain how you'll use it.
- If they don't have any, that's fine — move on.

**When to move on:**
After the user has shared what they have (or confirmed they don't have anything), include `[STAGE_COMPLETE]` at the end.
""",

    Stage.SIMULATION_PLAN: COACH_PERSONA + """
## YOUR CURRENT TASK: Stage 5 — The Simulation Plan

You have everything you need. Now formalize it into a simulation plan and present it to the user for confirmation.

**What to do:**
1. Summarize the entire plan in a clear, readable format
2. Present the JSON config for the simulation
3. Ask for final confirmation

**Your summary should include:**
- Product name and description
- Target market
- The archetypes (with percentages)
- The assumptions being tested
- The interview questions
- Simulation parameters (persona count, interview turns)

**IMPORTANT:** You MUST output a JSON block wrapped in ```json ... ``` tags containing the complete simulation config. Use this exact structure:

```json
{
  "product_name": "...",
  "product_description": "...",
  "target_market": "...",
  "assumptions": ["...", "..."],
  "questions": ["...", "..."],
  "archetypes": {
    "archetype_key": {
      "name": "Human Readable Name",
      "description": "Detailed description...",
      "percentage": 20
    }
  },
  "persona_count": 30,
  "interview_turns": 6
}
```

End with: "Does this look right? Reply **yes** to launch the simulation, or tell me what to change."

Include `[STAGE_COMPLETE]` at the end of your message.
""",
}


# ──────────────────────────────────────────────
# Session State
# ──────────────────────────────────────────────

class Session:
    """Tracks the state of a single user's simulation conversation."""

    def __init__(self, user_id: str, channel_id: str = None, thread_ts: str = None):
        self.user_id = user_id
        self.channel_id = channel_id
        self.thread_ts = thread_ts
        self.stage = Stage.IDLE
        self.messages: List[Dict[str, str]] = []  # Full conversation history
        self.config: Dict[str, Any] = {}  # The simulation config being built
        self.collected_data: List[str] = []  # User-provided data (transcripts, etc.)
        self.output_dir: Optional[str] = None
        self.started_at = datetime.now()

        # Stage-specific context that accumulates across stages
        self.context = {
            "product_summary": "",
            "value_prop": "",
            "archetypes_summary": "",
            "assumptions_summary": "",
            "data_summary": "",
        }

    def add_user_message(self, text: str):
        self.messages.append({"role": "user", "content": text})

    def add_assistant_message(self, text: str):
        # Strip the stage marker before storing
        clean_text = text.replace("[STAGE_COMPLETE]", "").strip()
        self.messages.append({"role": "assistant", "content": clean_text})

    def get_context_summary(self) -> str:
        """Build a running context summary from what's been gathered so far."""
        parts = []
        if self.context["product_summary"]:
            parts.append(f"**Product:** {self.context['product_summary']}")
        if self.context["value_prop"]:
            parts.append(f"**Value Prop:** {self.context['value_prop']}")
        if self.context["archetypes_summary"]:
            parts.append(f"**Archetypes:** {self.context['archetypes_summary']}")
        if self.context["assumptions_summary"]:
            parts.append(f"**Assumptions:** {self.context['assumptions_summary']}")
        if self.context["data_summary"]:
            parts.append(f"**User Data:** {self.context['data_summary']}")
        return "\n".join(parts) if parts else "No context gathered yet."


# ──────────────────────────────────────────────
# Core Conversation Engine
# ──────────────────────────────────────────────

class ConversationEngine:
    """
    Interface-agnostic conversation engine.

    This is the shared brain used by all interfaces (Slack, CLI, web).
    It manages sessions, routes messages through the stage-based flow,
    and produces responses via the LLM.
    """

    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.sessions: Dict[str, Session] = {}
        self.model = model

    def get_or_create_session(
        self, user_id: str, channel_id: str = None, thread_ts: str = None
    ) -> Session:
        """Get an existing session or create a new one."""
        if user_id not in self.sessions:
            self.sessions[user_id] = Session(user_id, channel_id, thread_ts)
        return self.sessions[user_id]

    def handle_message(self, user_id: str, message: str,
                       channel_id: str = None, thread_ts: str = None) -> str:
        """
        Process a user message and return the agent's response.

        This is the main entry point for all interfaces. It routes the message
        to the appropriate stage handler and returns a text response.

        Args:
            user_id: Unique identifier for the user.
            message: The user's message text.
            channel_id: Optional channel/room identifier.
            thread_ts: Optional thread identifier.

        Returns:
            The agent's response text.
        """
        session = self.get_or_create_session(user_id, channel_id, thread_ts)

        if session.stage == Stage.IDLE:
            return self._start_new_conversation(session, message)

        elif session.stage == Stage.CONFIRMING:
            return self._handle_confirmation(session, message)

        elif session.stage == Stage.RUNNING:
            return ":hourglass_flowing_sand: Your simulation is still running. I'll post the results when it's done."

        elif session.stage == Stage.COMPLETE:
            # Previous sim done — start fresh
            return self._start_new_conversation(session, message)

        else:
            # Active coaching stage
            return self._handle_coaching_stage(session, message)

    def start_new(self, user_id: str, initial_message: str = "",
                  channel_id: str = None, thread_ts: str = None) -> str:
        """
        Explicitly start a new simulation conversation.

        Args:
            user_id: Unique identifier for the user.
            initial_message: Optional initial context from the user.
            channel_id: Optional channel identifier.
            thread_ts: Optional thread identifier.

        Returns:
            The agent's opening response.
        """
        session = Session(user_id, channel_id, thread_ts)
        self.sessions[user_id] = session
        return self._start_new_conversation(session, initial_message)

    def get_status(self, user_id: str) -> str:
        """Get the current status of a user's session."""
        if user_id not in self.sessions:
            return "No active simulation. Start one by sending me a message about your product."

        session = self.sessions[user_id]
        status_map = {
            Stage.IDLE: "No active simulation. Send me a message to start.",
            Stage.IDEA_DUMP: ":memo: Stage 1/5 — We're exploring your idea. Keep chatting!",
            Stage.VALUE_PROP: ":dart: Stage 2/5 — Defining your value proposition.",
            Stage.CUSTOMER_SEGMENTS: ":busts_in_silhouette: Stage 3/5 — Mapping customer segments.",
            Stage.ASSUMPTIONS: ":thinking_face: Stage 4/5 — Identifying assumptions to test.",
            Stage.DATA_COLLECTION: ":file_folder: Collecting additional data (optional).",
            Stage.SIMULATION_PLAN: ":clipboard: Stage 5/5 — Finalizing the simulation plan.",
            Stage.CONFIRMING: ":eyes: Waiting for your confirmation to run.",
            Stage.RESEARCHING: ":mag: Building the world model with background research...",
            Stage.RUNNING: ":hourglass_flowing_sand: Simulation is running!",
            Stage.COMPLETE: ":white_check_mark: Last simulation is complete. Message me to start a new one.",
        }
        return status_map.get(session.stage, "Unknown state.")

    def cancel(self, user_id: str) -> str:
        """Cancel a user's current session."""
        if user_id not in self.sessions:
            return "No active simulation to cancel."
        session = self.sessions[user_id]
        if session.stage == Stage.RUNNING:
            session.stage = Stage.IDLE
            return ":stop_sign: Simulation marked as cancelled. The background process may still complete."
        else:
            session.stage = Stage.IDLE
            return ":stop_sign: Cancelled. Send me a message when you want to try again."

    def get_session_config(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get the confirmed simulation config for a user's session."""
        if user_id in self.sessions:
            return self.sessions[user_id].config
        return None

    def set_stage(self, user_id: str, stage: Stage):
        """Manually set a session's stage (used by interfaces for running/complete)."""
        if user_id in self.sessions:
            self.sessions[user_id].stage = stage

    # ──────────────────────────────────────────
    # Internal Methods
    # ──────────────────────────────────────────

    def _start_new_conversation(self, session: Session, initial_message: str) -> str:
        """Start a new coaching conversation."""
        session.stage = Stage.IDEA_DUMP
        session.messages = []
        session.config = {}
        session.context = {
            "product_summary": "",
            "value_prop": "",
            "archetypes_summary": "",
            "assumptions_summary": "",
            "data_summary": "",
        }

        if initial_message:
            session.add_user_message(initial_message)

        # Generate the opening response
        response = self._call_llm(session)

        # Check if the user gave us so much info we can skip ahead
        response, advanced = self._check_stage_complete(session, response)

        session.add_assistant_message(response)
        return self._clean_response(response)

    def _handle_coaching_stage(self, session: Session, message: str) -> str:
        """Handle a message during any active coaching stage."""
        session.add_user_message(message)

        response = self._call_llm(session)

        # Check if the stage is complete and advance if so
        response, advanced = self._check_stage_complete(session, response)

        session.add_assistant_message(response)

        # If we've reached the simulation plan stage and it has JSON, move to confirming
        if session.stage == Stage.SIMULATION_PLAN and "```json" in response:
            config_json = self._extract_json(response)
            if config_json:
                session.config = config_json
                session.stage = Stage.CONFIRMING

        return self._clean_response(response)

    def _handle_confirmation(self, session: Session, message: str) -> str:
        """Handle messages during the confirmation phase."""
        lower = message.lower().strip()

        affirmatives = {
            "yes", "y", "yep", "looks good", "run it", "go",
            "let's go", "lgtm", "confirmed", "confirm", "do it",
            "ship it", "send it", "launch", "perfect", "looks right",
        }

        if lower in affirmatives:
            session.stage = Stage.RUNNING
            return (
                ":rocket: *Simulation launching!* I'll build a world model, generate personas, "
                "run interviews, and synthesize the results. This usually takes 5-15 minutes. "
                "I'll post updates as I go."
            )

        elif lower in ("no", "cancel", "stop", "nevermind", "nah"):
            session.stage = Stage.IDLE
            return "No problem — cancelled. Just message me when you want to try again."

        else:
            # User wants to modify — go back to the simulation plan stage
            session.stage = Stage.SIMULATION_PLAN
            session.add_user_message(message)
            response = self._call_llm(session)
            response, _ = self._check_stage_complete(session, response)
            session.add_assistant_message(response)

            if "```json" in response:
                config_json = self._extract_json(response)
                if config_json:
                    session.config = config_json
                    session.stage = Stage.CONFIRMING

            return self._clean_response(response)

    def _check_stage_complete(self, session: Session, response: str) -> tuple:
        """
        Check if the LLM signaled stage completion and advance if so.

        Returns:
            (response_text, did_advance: bool)
        """
        if "[STAGE_COMPLETE]" not in response:
            return response, False

        # Extract the summary from this stage's response for context
        clean_response = response.replace("[STAGE_COMPLETE]", "").strip()
        self._update_context(session, clean_response)

        # Determine the next stage
        stage_order = [
            Stage.IDEA_DUMP,
            Stage.VALUE_PROP,
            Stage.CUSTOMER_SEGMENTS,
            Stage.ASSUMPTIONS,
            Stage.DATA_COLLECTION,
            Stage.SIMULATION_PLAN,
        ]

        current_idx = stage_order.index(session.stage) if session.stage in stage_order else -1
        if current_idx >= 0 and current_idx < len(stage_order) - 1:
            next_stage = stage_order[current_idx + 1]
            session.stage = next_stage
            logger.info(
                "Session %s advancing from %s to %s",
                session.user_id, stage_order[current_idx].value, next_stage.value,
            )

        return clean_response, True

    def _update_context(self, session: Session, response: str):
        """Update the session's running context based on the current stage."""
        # Use the LLM to extract a concise summary of what was gathered
        summary_prompt = f"""Based on this conversation excerpt, provide a 2-3 sentence summary of the key information gathered. Be concise and factual.

Conversation excerpt:
{response}"""

        try:
            summary = chat_completion(
                messages=[{"role": "user", "content": summary_prompt}],
                model=self.model,
                temperature=0.3,
                max_tokens=200,
            )

            stage_to_context = {
                Stage.IDEA_DUMP: "product_summary",
                Stage.VALUE_PROP: "value_prop",
                Stage.CUSTOMER_SEGMENTS: "archetypes_summary",
                Stage.ASSUMPTIONS: "assumptions_summary",
                Stage.DATA_COLLECTION: "data_summary",
            }

            context_key = stage_to_context.get(session.stage)
            if context_key:
                session.context[context_key] = summary
        except Exception as e:
            logger.error("Failed to update context summary: %s", e)

    def _call_llm(self, session: Session) -> str:
        """Call the LLM with the current stage prompt and conversation history."""
        # Get the stage-specific system prompt
        system_prompt = STAGE_PROMPTS.get(session.stage, COACH_PERSONA)

        # Add accumulated context
        context_summary = session.get_context_summary()
        if context_summary != "No context gathered yet.":
            system_prompt += f"\n\n## CONTEXT GATHERED SO FAR:\n{context_summary}"

        messages = [{"role": "system", "content": system_prompt}] + session.messages

        try:
            return chat_completion(
                messages=messages,
                model=self.model,
                temperature=0.7,
                max_tokens=2000,
            )
        except Exception as e:
            logger.error("LLM call failed: %s", e)
            return f"Sorry, I hit an error: {str(e)}. Try sending your message again?"

    def _extract_json(self, text: str) -> Optional[Dict]:
        """Extract a JSON config from the LLM's response."""
        try:
            # Try the standard ```json ... ``` block first
            match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
            if match:
                return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

        try:
            # Fallback: find the largest {...} block
            matches = re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
            if matches:
                largest = max(matches, key=len)
                return json.loads(largest)
        except json.JSONDecodeError:
            pass

        logger.error("Failed to extract JSON from LLM response")
        return None

    def _clean_response(self, text: str) -> str:
        """Remove internal markers from the response before sending to the user."""
        return text.replace("[STAGE_COMPLETE]", "").strip()
