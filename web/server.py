#!/usr/bin/env python3
"""
Market Simulator — Web Interface (FastAPI Backend)

A simple web server that exposes the ConversationEngine via:
  - WebSocket for real-time conversational flow
  - REST endpoints for status and config management

Serves the static frontend from web/static/.
"""
import os
import sys
import json
import asyncio
import logging
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.conversation_engine import ConversationEngine, Stage
from core.simulation_bridge import SimulationBridge

# ── Setup ──
logging.basicConfig(
    level=os.environ.get("SIM_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("market_sim.web")

# ── Initialize ──
app = FastAPI(title="Market Simulator", version="1.0.0")
engine = ConversationEngine(model=os.environ.get("SIM_MODEL", "gemini-2.5-flash"))
bridge = SimulationBridge()

# Static files directory
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


# ──────────────────────────────────────────────
# REST Endpoints
# ──────────────────────────────────────────────

@app.get("/")
async def serve_index():
    """Serve the main HTML page."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/sessions/{session_id}/status")
async def get_status(session_id: str):
    """Get the status of a session."""
    status = engine.get_status(session_id)
    session = engine.sessions.get(session_id)
    return {
        "status": status,
        "stage": session.stage.value if session else "idle",
    }


# ──────────────────────────────────────────────
# WebSocket — Conversational Interface
# ──────────────────────────────────────────────

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str = None):
    """
    WebSocket endpoint for the conversational flow.

    Messages from client:
      {"type": "message", "text": "user's message"}
      {"type": "start", "text": "optional initial context"}
      {"type": "cancel"}

    Messages to client:
      {"type": "agent", "text": "agent's response", "stage": "current_stage"}
      {"type": "progress", "text": "simulation progress update"}
      {"type": "result", "text": "simulation results", "files": [...]}
      {"type": "error", "text": "error message"}
    """
    await websocket.accept()

    if not session_id:
        session_id = str(uuid.uuid4())

    logger.info("WebSocket connected: session=%s", session_id)

    try:
        # Send initial greeting
        response = engine.start_new(session_id, "")
        if not response or response.strip() == "":
            response = (
                "👋 Hey! I'm the Market Simulator — your thinking partner for "
                "validating product assumptions.\n\n"
                "Tell me about the product or idea you want to test. "
                "What are you building, and who is it for?"
            )

        await websocket.send_json({
            "type": "agent",
            "text": _clean_emoji(response),
            "stage": "idea_dump",
        })

        # Message loop
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "message")

            if msg_type == "cancel":
                result = engine.cancel(session_id)
                await websocket.send_json({
                    "type": "agent",
                    "text": result,
                    "stage": "idle",
                })
                continue

            text = data.get("text", "").strip()
            if not text:
                continue

            # Process through conversation engine
            response = engine.handle_message(session_id, text)
            session = engine.sessions.get(session_id)
            current_stage = session.stage.value if session else "idle"

            await websocket.send_json({
                "type": "agent",
                "text": _clean_emoji(response),
                "stage": current_stage,
            })

            # Check if simulation should launch
            if session and session.stage == Stage.RUNNING:
                await _run_simulation_ws(session_id, websocket)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session=%s", session_id)
    except Exception as e:
        logger.error("WebSocket error: %s", e, exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "text": f"An error occurred: {str(e)[:200]}",
            })
        except Exception:
            pass


async def _run_simulation_ws(session_id: str, websocket: WebSocket):
    """Run the simulation and stream progress via WebSocket."""
    config_json = engine.get_session_config(session_id)
    if not config_json:
        await websocket.send_json({
            "type": "error",
            "text": "No simulation config found. Something went wrong.",
        })
        engine.set_stage(session_id, Stage.IDLE)
        return

    try:
        config = bridge.build_config(config_json)

        async def progress_callback(msg: str):
            try:
                await websocket.send_json({
                    "type": "progress",
                    "text": _clean_emoji(msg),
                })
            except Exception:
                pass

        results = await bridge.run_simulation(config, progress_callback)

        if results.get("success"):
            # Read the report
            report_text = ""
            report_path = results.get("report_path")
            if report_path and os.path.exists(report_path):
                with open(report_path, "r") as f:
                    report_text = f.read()

            await websocket.send_json({
                "type": "result",
                "text": report_text,
                "files": {
                    "report": results.get("report_path"),
                    "transcripts": results.get("transcripts_path"),
                    "audience": results.get("audience_path"),
                    "quantitative": results.get("quantitative_path"),
                    "insights": results.get("insights_path"),
                },
                "summary": {
                    "personas": results.get("personas_count", 0),
                    "interviews": results.get("interviews_count", 0),
                },
            })
            engine.set_stage(session_id, Stage.COMPLETE)
        else:
            error = results.get("error", "Unknown error")
            await websocket.send_json({
                "type": "error",
                "text": f"Simulation failed: {error}",
            })
            engine.set_stage(session_id, Stage.IDLE)

    except Exception as e:
        logger.error("Simulation failed: %s", e, exc_info=True)
        await websocket.send_json({
            "type": "error",
            "text": f"Simulation crashed: {str(e)[:200]}",
        })
        engine.set_stage(session_id, Stage.IDLE)


def _clean_emoji(text: str) -> str:
    """Convert Slack-style emoji to Unicode for web display."""
    replacements = {
        ":wave:": "👋", ":rocket:": "🚀", ":white_check_mark:": "✅",
        ":x:": "❌", ":hourglass_flowing_sand:": "⏳", ":earth_americas:": "🌎",
        ":busts_in_silhouette:": "👥", ":speech_balloon:": "💬",
        ":bar_chart:": "📊", ":tada:": "🎉", ":memo:": "📝",
        ":dart:": "🎯", ":thinking_face:": "🤔", ":file_folder:": "📁",
        ":clipboard:": "📋", ":eyes:": "👀", ":stop_sign:": "🛑",
        ":mag:": "🔍", ":page_facing_up:": "📄", ":bulb:": "💡",
        ":warning:": "⚠️", ":star:": "⭐", ":fire:": "🔥",
    }
    for slack, unicode in replacements.items():
        text = text.replace(slack, unicode)
    return text


# Mount static files (after routes so routes take priority)
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("WEB_PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
