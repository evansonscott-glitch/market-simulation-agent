#!/usr/bin/env python3
"""
Market Simulator — Slack Bot

A conversational Slack bot that guides users through setting up and running
market simulations. Uses Socket Mode for easy deployment (no public URL needed).

The bot acts as a thinking partner: it asks questions to understand the product,
target market, and assumptions, then builds a config, runs the simulation,
and posts the synthesized results back to Slack.
"""
import os
import sys
import logging
import threading

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from conversation import ConversationManager

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("slack_bot")

# ── Environment Validation ──
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if not SLACK_BOT_TOKEN:
    logger.error("SLACK_BOT_TOKEN not set. Set it in your environment.")
    sys.exit(1)
if not SLACK_APP_TOKEN:
    logger.error("SLACK_APP_TOKEN not set. Set it in your environment.")
    sys.exit(1)
if not OPENAI_API_KEY:
    logger.error("OPENAI_API_KEY not set. Set it in your environment.")
    sys.exit(1)

# ── Initialize App ──
app = App(token=SLACK_BOT_TOKEN)
conversation_manager = ConversationManager()


# ──────────────────────────────────────────────
# Event Handlers
# ──────────────────────────────────────────────

@app.event("app_mention")
def handle_mention(event, say, client):
    """Handle @mentions of the bot in channels."""
    user_id = event["user"]
    channel_id = event["channel"]
    text = event.get("text", "").strip()
    thread_ts = event.get("thread_ts", event["ts"])

    # Remove the bot mention from the text
    # Text comes in as "<@BOT_ID> actual message"
    parts = text.split(">", 1)
    user_message = parts[1].strip() if len(parts) > 1 else text

    logger.info("Mention from user=%s channel=%s: %s", user_id, channel_id, user_message[:100])

    response = conversation_manager.handle_message(
        user_id=user_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
        message=user_message,
        say=say,
        client=client,
    )


@app.event("message")
def handle_dm(event, say, client):
    """Handle direct messages to the bot."""
    # Ignore bot messages to prevent loops
    if event.get("bot_id") or event.get("subtype"):
        return

    user_id = event["user"]
    channel_id = event["channel"]
    text = event.get("text", "").strip()
    thread_ts = event.get("thread_ts", event["ts"])

    logger.info("DM from user=%s: %s", user_id, text[:100])

    response = conversation_manager.handle_message(
        user_id=user_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
        message=text,
        say=say,
        client=client,
    )


@app.command("/simulate")
def handle_simulate_command(ack, command, say, client):
    """Handle the /simulate slash command to start a new simulation."""
    ack()
    user_id = command["user_id"]
    channel_id = command["channel_id"]
    text = command.get("text", "").strip()

    logger.info("/simulate from user=%s: %s", user_id, text[:100])

    # Start a new conversation
    conversation_manager.start_new_simulation(
        user_id=user_id,
        channel_id=channel_id,
        initial_context=text,
        say=say,
        client=client,
    )


@app.command("/sim-status")
def handle_status_command(ack, command, say):
    """Check the status of a running simulation."""
    ack()
    user_id = command["user_id"]
    status = conversation_manager.get_status(user_id)
    say(text=status)


@app.command("/sim-cancel")
def handle_cancel_command(ack, command, say):
    """Cancel a running simulation."""
    ack()
    user_id = command["user_id"]
    result = conversation_manager.cancel_simulation(user_id)
    say(text=result)


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting Market Simulator Slack Bot...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
