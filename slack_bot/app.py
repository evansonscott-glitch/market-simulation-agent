"""
Market Simulator — Slack Bot Interface

Thin Slack interface layer that delegates all conversation logic to the
core ConversationEngine and simulation execution to the SimulationBridge.

Uses Socket Mode (no public URL required) for easy deployment.

Commands:
  /simulate       — Start a new simulation
  /sim-status     — Check current simulation status
  /sim-cancel     — Cancel the current simulation

Also responds to:
  - Direct messages
  - @mentions in channels
"""
import os
import re
import sys
import asyncio
import threading
import logging

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from core.conversation_engine import ConversationEngine, Stage
from core.simulation_bridge import SimulationBridge

# ── Setup ──
logging.basicConfig(
    level=os.environ.get("SIM_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("market_sim.slack")

# ── Environment Validation ──
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if not SLACK_BOT_TOKEN:
    logger.error("SLACK_BOT_TOKEN not set. See SLACK_SETUP.md for instructions.")
    sys.exit(1)
if not SLACK_APP_TOKEN:
    logger.error("SLACK_APP_TOKEN not set. See SLACK_SETUP.md for instructions.")
    sys.exit(1)
if not OPENAI_API_KEY:
    logger.error("OPENAI_API_KEY not set. Set it in your environment.")
    sys.exit(1)

# ── Initialize ──
app = App(token=SLACK_BOT_TOKEN)
engine = ConversationEngine(model=os.environ.get("SIM_MODEL", "gemini-2.5-flash"))
bridge = SimulationBridge()


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def get_user_key(user_id: str, channel_id: str = None, thread_ts: str = None) -> str:
    """Create a unique session key. Thread-based if in a thread, else user-based."""
    if thread_ts:
        return f"{user_id}:{channel_id}:{thread_ts}"
    return user_id


def send_long_message(say_fn, text: str, thread_ts: str = None):
    """Send a message, splitting if it exceeds Slack's 4000 char limit."""
    max_len = 3900
    kwargs = {}
    if thread_ts:
        kwargs["thread_ts"] = thread_ts

    if len(text) <= max_len:
        say_fn(text=text, **kwargs)
        return

    # Split on paragraph boundaries
    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            chunks.append(current)
            current = line
        else:
            current += "\n" + line if current else line
    if current:
        chunks.append(current)

    for chunk in chunks:
        say_fn(text=chunk, **kwargs)


def run_simulation_background(user_key: str, say_fn, channel_id: str, thread_ts: str = None):
    """Run the simulation in a background thread."""

    def _run():
        config_json = engine.get_session_config(user_key)
        if not config_json:
            say_fn(
                text=":x: No simulation config found. Something went wrong.",
                thread_ts=thread_ts,
            )
            engine.set_stage(user_key, Stage.IDLE)
            return

        try:
            # Build the full simulation config
            config = bridge.build_config(config_json)

            # Create async progress callback
            async def progress_callback(msg: str):
                say_fn(text=msg, thread_ts=thread_ts)

            # Run the simulation in an event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                results = loop.run_until_complete(
                    bridge.run_simulation(config, progress_callback)
                )
            finally:
                loop.close()

            if results.get("success"):
                # Post the report
                report_path = results.get("report_path")
                if report_path and os.path.exists(report_path):
                    with open(report_path, "r") as f:
                        report = f.read()

                    # Post a summary
                    summary = report[:3000]
                    if len(report) > 3000:
                        summary += "\n\n_... (report truncated — see full file below)_"
                    send_long_message(say_fn, summary, thread_ts)

                    # Upload the full report as a file
                    try:
                        app.client.files_upload_v2(
                            channel=channel_id,
                            thread_ts=thread_ts,
                            file=report_path,
                            title="Simulation Report",
                            initial_comment=":page_facing_up: Full simulation report attached.",
                        )
                    except Exception as e:
                        logger.error("Failed to upload report file: %s", e)

                    # Upload transcripts if available
                    transcripts_path = results.get("transcripts_path")
                    if transcripts_path and os.path.exists(transcripts_path):
                        try:
                            app.client.files_upload_v2(
                                channel=channel_id,
                                thread_ts=thread_ts,
                                file=transcripts_path,
                                title="Interview Transcripts",
                                initial_comment=":speech_balloon: Full interview transcripts.",
                            )
                        except Exception as e:
                            logger.error("Failed to upload transcripts: %s", e)

                engine.set_stage(user_key, Stage.COMPLETE)
                say_fn(
                    text=(
                        f":white_check_mark: *Simulation complete!* "
                        f"{results.get('interviews_count', 0)} interviews analyzed.\n\n"
                        f"Send me another message to start a new simulation."
                    ),
                    thread_ts=thread_ts,
                )
            else:
                error = results.get("error", "Unknown error")
                say_fn(
                    text=f":x: Simulation failed: {error}",
                    thread_ts=thread_ts,
                )
                engine.set_stage(user_key, Stage.IDLE)

        except Exception as e:
            logger.error("Simulation thread crashed: %s", e, exc_info=True)
            say_fn(
                text=f":x: Simulation crashed: {str(e)[:200]}",
                thread_ts=thread_ts,
            )
            engine.set_stage(user_key, Stage.IDLE)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


def process_message(user_id, channel_id, text, thread_ts, say):
    """Shared message processing logic for mentions and DMs."""
    if not text:
        return

    user_key = get_user_key(user_id, channel_id, thread_ts)
    response = engine.handle_message(user_key, text, channel_id, thread_ts)

    # Check if the simulation should be launched
    session = engine.sessions.get(user_key)
    if session and session.stage == Stage.RUNNING:
        send_long_message(say, response, thread_ts)
        run_simulation_background(user_key, say, channel_id, thread_ts)
    else:
        send_long_message(say, response, thread_ts)


# ──────────────────────────────────────────────
# Slash Commands
# ──────────────────────────────────────────────

@app.command("/simulate")
def handle_simulate(ack, command, say):
    """Start a new simulation."""
    ack()
    user_id = command["user_id"]
    channel_id = command["channel_id"]
    initial_text = command.get("text", "").strip()
    user_key = get_user_key(user_id, channel_id)

    if initial_text:
        response = engine.start_new(user_key, initial_text, channel_id)
    else:
        response = engine.start_new(user_key, "", channel_id)
        if not response or response.strip() == "":
            response = (
                ":wave: Hey! I'm the Market Simulator — your thinking partner for "
                "validating product assumptions.\n\n"
                "Tell me about the product or idea you want to test. "
                "What are you building, and who is it for?"
            )

    send_long_message(say, response)


@app.command("/sim-status")
def handle_status(ack, command, say):
    """Check simulation status."""
    ack()
    user_key = get_user_key(command["user_id"], command["channel_id"])
    status = engine.get_status(user_key)
    say(text=status)


@app.command("/sim-cancel")
def handle_cancel(ack, command, say):
    """Cancel current simulation."""
    ack()
    user_key = get_user_key(command["user_id"], command["channel_id"])
    result = engine.cancel(user_key)
    say(text=result)


# ──────────────────────────────────────────────
# Message Handlers
# ──────────────────────────────────────────────

@app.event("app_mention")
def handle_mention(event, say):
    """Handle @mentions in channels."""
    user_id = event.get("user")
    channel_id = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    text = event.get("text", "")

    # Strip the bot mention from the text
    text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()

    if not text:
        say(
            text=(
                ":wave: Hey! I'm the Market Simulator. Tell me about a product or idea "
                "you want to test, and I'll help you design and run a simulated customer "
                "interview campaign.\n\nYou can also use `/simulate` to get started."
            ),
            thread_ts=thread_ts,
        )
        return

    process_message(user_id, channel_id, text, thread_ts, say)


@app.event("message")
def handle_dm(event, say):
    """Handle direct messages."""
    if event.get("subtype") or event.get("bot_id"):
        return

    user_id = event.get("user")
    channel_id = event.get("channel")
    thread_ts = event.get("thread_ts")
    text = event.get("text", "").strip()

    process_message(user_id, channel_id, text, thread_ts, say)


# ──────────────────────────────────────────────
# Entry Point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting Market Simulator Slack bot...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
