"""
Market Simulator — Conversation State Machine

Manages the conversational flow for gathering simulation inputs from users.
Uses an LLM to act as a thinking partner — asking smart questions, helping
users articulate assumptions, and building the simulation config dynamically.

States:
  IDLE         → No active simulation
  GATHERING    → Asking questions to build the simulation config
  CONFIRMING   → User reviews the config before running
  RESEARCHING  → Building the world model via web research
  RUNNING      → Simulation is in progress
  COMPLETE     → Results are ready
"""
import os
import sys
import json
import threading
import traceback
from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime

# Add the parent directory to the path so we can import the simulation engine
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import OpenAI

import logging
logger = logging.getLogger("conversation")


class ConversationState(Enum):
    IDLE = "idle"
    GATHERING = "gathering"
    CONFIRMING = "confirming"
    RESEARCHING = "researching"
    RUNNING = "running"
    COMPLETE = "complete"


# ──────────────────────────────────────────────
# System Prompts
# ──────────────────────────────────────────────

GATHERING_SYSTEM_PROMPT = """You are the Market Simulator bot — a thinking partner that helps venture capital investors and founders validate product assumptions through simulated customer interviews.

Your job right now is to gather the information needed to run a market simulation. You need to collect:

1. **Product Name** — What is the product or company being tested?
2. **Product Description** — What does it do? What's the value prop? Include pricing if known.
3. **Target Market** — Who is the customer? Be specific about roles, company sizes, industries.
4. **Assumptions to Test** — What does the user believe to be true that they want to validate? Help them articulate 3-5 testable assumptions.
5. **Key Questions** — What specific questions should the simulated personas be asked? Help craft 3-5 good ones.
6. **Persona Archetypes** — What types of people should be in the simulated audience? Suggest 4-6 archetypes based on the target market.

IMPORTANT GUIDELINES:
- Be conversational and natural. You're a smart colleague, not a form.
- Ask follow-up questions to get specifics. Vague inputs produce vague simulations.
- Help the user think through their assumptions. If they say something fuzzy like "people would like this," push them to be more specific: "like it enough to pay $X/month?" or "prefer it over their current workflow?"
- You can gather multiple pieces of information in a single exchange — don't be overly rigid about one-question-at-a-time.
- When you have enough information, say so and present a summary for confirmation.
- Keep messages concise — this is Slack, not email. Use bullet points and formatting.

WHEN YOU HAVE ENOUGH INFORMATION:
Output a JSON block wrapped in ```json ... ``` tags containing the complete simulation config. The user will be asked to confirm before the simulation runs.

The JSON should follow this structure:
{
  "product_name": "...",
  "product_description": "...",
  "target_market": "...",
  "assumptions": ["...", "..."],
  "questions": ["...", "..."],
  "archetypes": {
    "archetype_key": {
      "name": "Human Readable Name",
      "description": "Detailed description of this persona type...",
      "percentage": 20
    }
  },
  "persona_count": 30,
  "interview_turns": 6
}

CURRENT CONVERSATION CONTEXT:
"""

RESEARCH_PROMPT = """Based on the following product and market information, generate a comprehensive world model document that provides context for simulating customer interviews.

The world model should cover:
1. Industry landscape and key trends
2. Competitive alternatives and their strengths/weaknesses
3. Common pain points and workflows of the target audience
4. Typical objections and concerns buyers have
5. Pricing benchmarks in the market
6. Technology adoption patterns in this segment

Be factual and specific. This document will be used to make simulated personas more realistic.

PRODUCT AND MARKET INFO:
{config_summary}
"""


class UserSession:
    """Tracks the state of a single user's simulation conversation."""

    def __init__(self, user_id: str, channel_id: str, thread_ts: str = None):
        self.user_id = user_id
        self.channel_id = channel_id
        self.thread_ts = thread_ts
        self.state = ConversationState.IDLE
        self.messages = []  # Conversation history for the LLM
        self.config = {}  # The simulation config being built
        self.output_dir = None  # Where results are saved
        self.started_at = datetime.now()
        self.sim_thread = None  # Background thread for simulation

    def add_user_message(self, text: str):
        self.messages.append({"role": "user", "content": text})

    def add_assistant_message(self, text: str):
        self.messages.append({"role": "assistant", "content": text})


class ConversationManager:
    """Manages all active user conversations."""

    def __init__(self):
        self.sessions: Dict[str, UserSession] = {}
        self.client = OpenAI()  # Uses OPENAI_API_KEY env var
        self.model = "gemini-2.5-flash"

    def _get_or_create_session(self, user_id: str, channel_id: str, thread_ts: str = None) -> UserSession:
        """Get an existing session or create a new one."""
        if user_id not in self.sessions:
            self.sessions[user_id] = UserSession(user_id, channel_id, thread_ts)
        return self.sessions[user_id]

    def handle_message(self, user_id: str, channel_id: str, thread_ts: str,
                       message: str, say, client):
        """Route an incoming message to the appropriate handler based on state."""
        session = self._get_or_create_session(user_id, channel_id, thread_ts)

        if session.state == ConversationState.IDLE:
            # No active simulation — treat as a new simulation request
            self.start_new_simulation(user_id, channel_id, message, say, client, thread_ts)

        elif session.state == ConversationState.GATHERING:
            self._handle_gathering(session, message, say, thread_ts)

        elif session.state == ConversationState.CONFIRMING:
            self._handle_confirming(session, message, say, client, thread_ts)

        elif session.state == ConversationState.RUNNING:
            say(
                text=":hourglass_flowing_sand: Your simulation is still running. I'll post the results here when it's done. Use `/sim-status` to check progress.",
                thread_ts=thread_ts,
            )

        elif session.state == ConversationState.COMPLETE:
            # Previous sim is done — start a new one
            self.start_new_simulation(user_id, channel_id, message, say, client, thread_ts)

    def start_new_simulation(self, user_id: str, channel_id: str,
                             initial_context: str, say, client, thread_ts: str = None):
        """Start a new simulation conversation."""
        session = UserSession(user_id, channel_id, thread_ts)
        session.state = ConversationState.GATHERING
        self.sessions[user_id] = session

        # Build the initial prompt
        if initial_context:
            session.add_user_message(initial_context)
            intro = f"The user wants to run a simulation. Here's what they said: \"{initial_context}\""
        else:
            intro = "The user wants to run a new market simulation but hasn't provided details yet. Start by asking what product or company they want to test."

        # Get the LLM's first response
        response = self._call_llm(session, intro if not initial_context else None)
        session.add_assistant_message(response)

        say(text=response, thread_ts=thread_ts)

    def _handle_gathering(self, session: UserSession, message: str, say, thread_ts: str):
        """Handle messages during the information gathering phase."""
        session.add_user_message(message)

        response = self._call_llm(session)
        session.add_assistant_message(response)

        # Check if the LLM produced a config JSON (signal that gathering is complete)
        if "```json" in response:
            config_json = self._extract_json(response)
            if config_json:
                session.config = config_json
                session.state = ConversationState.CONFIRMING
                # The LLM's response already contains the summary + JSON
                say(text=response, thread_ts=thread_ts)
                say(
                    text=":point_up: Does this look right? Reply *yes* to run the simulation, or tell me what to change.",
                    thread_ts=thread_ts,
                )
                return

        say(text=response, thread_ts=thread_ts)

    def _handle_confirming(self, session: UserSession, message: str, say, client, thread_ts: str):
        """Handle messages during the confirmation phase."""
        lower = message.lower().strip()

        if lower in ("yes", "y", "yep", "looks good", "run it", "go", "let's go", "lgtm", "confirmed", "confirm"):
            # User confirmed — start the simulation
            session.state = ConversationState.RUNNING
            say(
                text=":rocket: *Simulation starting!* I'll build a world model, generate personas, run interviews, and synthesize the results. This usually takes 5-15 minutes depending on the persona count. I'll post updates as I go.",
                thread_ts=thread_ts,
            )

            # Run simulation in background thread
            session.sim_thread = threading.Thread(
                target=self._run_simulation_background,
                args=(session, say, client, thread_ts),
                daemon=True,
            )
            session.sim_thread.start()

        elif lower in ("no", "cancel", "stop", "nevermind"):
            session.state = ConversationState.IDLE
            say(text="No problem — simulation cancelled. Just message me when you want to try again.", thread_ts=thread_ts)

        else:
            # User wants to modify something — go back to gathering
            session.state = ConversationState.GATHERING
            session.add_user_message(message)
            response = self._call_llm(session)
            session.add_assistant_message(response)

            if "```json" in response:
                config_json = self._extract_json(response)
                if config_json:
                    session.config = config_json
                    session.state = ConversationState.CONFIRMING
                    say(text=response, thread_ts=thread_ts)
                    say(
                        text=":point_up: Updated config. Does this look right now? Reply *yes* to run, or tell me what else to change.",
                        thread_ts=thread_ts,
                    )
                    return

            say(text=response, thread_ts=thread_ts)

    def _run_simulation_background(self, session: UserSession, say, client, thread_ts: str):
        """Run the full simulation pipeline in a background thread."""
        try:
            from simulation_runner import run_simulation_from_config
            result = run_simulation_from_config(
                config=session.config,
                progress_callback=lambda msg: say(text=msg, thread_ts=thread_ts),
            )

            session.state = ConversationState.COMPLETE
            session.output_dir = result["output_dir"]

            # Post the results
            self._post_results(session, result, say, client, thread_ts)

        except Exception as e:
            logger.error("Simulation failed: %s\n%s", e, traceback.format_exc())
            session.state = ConversationState.COMPLETE
            say(
                text=f":x: *Simulation failed:* {str(e)}\n\nYou can try again with `/simulate` or message me.",
                thread_ts=thread_ts,
            )

    def _post_results(self, session: UserSession, result: dict, say, client, thread_ts: str):
        """Post simulation results back to Slack in a readable format."""
        report = result.get("report", "No report generated.")
        insights = result.get("insights", {})
        output_dir = result.get("output_dir", "")

        # Post the executive summary
        say(
            text=":white_check_mark: *Simulation Complete!*",
            thread_ts=thread_ts,
        )

        # Break the report into chunks if it's too long for Slack (4000 char limit)
        max_len = 3800
        if len(report) <= max_len:
            say(text=report, thread_ts=thread_ts)
        else:
            # Split into sections by ## headers
            sections = report.split("\n## ")
            current_chunk = ""
            for i, section in enumerate(sections):
                section_text = section if i == 0 else f"## {section}"
                if len(current_chunk) + len(section_text) > max_len:
                    if current_chunk:
                        say(text=current_chunk, thread_ts=thread_ts)
                    current_chunk = section_text
                else:
                    current_chunk += f"\n{section_text}" if current_chunk else section_text
            if current_chunk:
                say(text=current_chunk, thread_ts=thread_ts)

        # Upload the full report as a file
        report_path = os.path.join(output_dir, "report.md")
        if os.path.exists(report_path):
            try:
                client.files_upload_v2(
                    channel=session.channel_id,
                    file=report_path,
                    title="Full Simulation Report",
                    initial_comment="Here's the full report as a downloadable file.",
                    thread_ts=thread_ts,
                )
            except Exception as e:
                logger.error("Failed to upload report file: %s", e)

        # Upload transcripts if they exist
        transcripts_path = os.path.join(output_dir, "transcripts.md")
        if os.path.exists(transcripts_path):
            try:
                client.files_upload_v2(
                    channel=session.channel_id,
                    file=transcripts_path,
                    title="Interview Transcripts",
                    initial_comment="Full interview transcripts for reference.",
                    thread_ts=thread_ts,
                )
            except Exception as e:
                logger.error("Failed to upload transcripts: %s", e)

        say(
            text=":bulb: Want to run another simulation? Just message me or use `/simulate`.",
            thread_ts=thread_ts,
        )

    def _call_llm(self, session: UserSession, system_addendum: str = None) -> str:
        """Call the LLM with the current conversation history."""
        system_content = GATHERING_SYSTEM_PROMPT
        if system_addendum:
            system_content += f"\n{system_addendum}"

        messages = [{"role": "system", "content": system_content}] + session.messages

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error("LLM call failed: %s", e)
            return f"Sorry, I hit an error talking to the AI: {str(e)}. Try again?"

    def _extract_json(self, text: str) -> Optional[dict]:
        """Extract a JSON config from the LLM's response."""
        try:
            start = text.index("```json") + 7
            end = text.index("```", start)
            json_str = text[start:end].strip()
            return json.loads(json_str)
        except (ValueError, json.JSONDecodeError) as e:
            logger.error("Failed to extract JSON from LLM response: %s", e)
            return None

    def get_status(self, user_id: str) -> str:
        """Get the status of a user's current simulation."""
        if user_id not in self.sessions:
            return "No active simulation. Use `/simulate` to start one."

        session = self.sessions[user_id]
        state_messages = {
            ConversationState.IDLE: "No active simulation. Use `/simulate` to start one.",
            ConversationState.GATHERING: ":memo: Gathering information for your simulation. Keep chatting with me!",
            ConversationState.CONFIRMING: ":eyes: Waiting for your confirmation to run the simulation.",
            ConversationState.RESEARCHING: ":mag: Building the world model with background research...",
            ConversationState.RUNNING: ":hourglass_flowing_sand: Simulation is running. Hang tight!",
            ConversationState.COMPLETE: ":white_check_mark: Last simulation is complete. Message me to start a new one.",
        }
        return state_messages.get(session.state, "Unknown state.")

    def cancel_simulation(self, user_id: str) -> str:
        """Cancel a user's current simulation."""
        if user_id not in self.sessions:
            return "No active simulation to cancel."

        session = self.sessions[user_id]
        if session.state == ConversationState.RUNNING:
            # Can't easily kill a running simulation, but we can mark it
            session.state = ConversationState.IDLE
            return ":stop_sign: Simulation marked as cancelled. Note: the background process may still complete, but results won't be posted."
        else:
            session.state = ConversationState.IDLE
            return ":stop_sign: Simulation cancelled. Use `/simulate` to start a new one."
