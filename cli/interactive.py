#!/usr/bin/env python3
"""
Market Simulator — Interactive CLI Interface

A terminal-based conversational interface that uses the same core
ConversationEngine as the Slack bot. Guides users through the five-stage
coaching flow and runs simulations from the command line.

Usage:
  python cli/interactive.py                    # Start interactive session
  python cli/interactive.py --config path.yaml # Run from existing config
"""
import os
import sys
import asyncio
import argparse
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.conversation_engine import ConversationEngine, Stage
from core.simulation_bridge import SimulationBridge

# ── Setup ──
logging.basicConfig(
    level=os.environ.get("SIM_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("market_sim.cli")

# ── Colors for terminal output ──
class Colors:
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def print_agent(text: str):
    """Print agent messages in blue."""
    # Replace Slack emoji with terminal equivalents
    text = text.replace(":wave:", "👋")
    text = text.replace(":rocket:", "🚀")
    text = text.replace(":white_check_mark:", "✅")
    text = text.replace(":x:", "❌")
    text = text.replace(":hourglass_flowing_sand:", "⏳")
    text = text.replace(":earth_americas:", "🌎")
    text = text.replace(":busts_in_silhouette:", "👥")
    text = text.replace(":speech_balloon:", "💬")
    text = text.replace(":bar_chart:", "📊")
    text = text.replace(":tada:", "🎉")
    text = text.replace(":memo:", "📝")
    text = text.replace(":dart:", "🎯")
    text = text.replace(":thinking_face:", "🤔")
    text = text.replace(":file_folder:", "📁")
    text = text.replace(":clipboard:", "📋")
    text = text.replace(":eyes:", "👀")
    text = text.replace(":stop_sign:", "🛑")
    text = text.replace(":mag:", "🔍")
    text = text.replace(":page_facing_up:", "📄")

    print(f"\n{Colors.BLUE}{Colors.BOLD}Market Simulator:{Colors.RESET}")
    print(f"{Colors.BLUE}{text}{Colors.RESET}")


def print_status(text: str):
    """Print status messages in yellow."""
    print(f"{Colors.YELLOW}{text}{Colors.RESET}")


def print_error(text: str):
    """Print error messages in red."""
    print(f"{Colors.RED}{text}{Colors.RESET}")


def print_header():
    """Print the CLI header."""
    print(f"""
{Colors.BOLD}╔══════════════════════════════════════════════════════╗
║           Market Simulator — Interactive CLI          ║
║                                                      ║
║  Your thinking partner for validating product         ║
║  assumptions through simulated customer interviews.   ║
╚══════════════════════════════════════════════════════╝{Colors.RESET}

{Colors.DIM}Commands:
  /status   — Check current stage
  /cancel   — Cancel and start over
  /quit     — Exit the CLI
{Colors.RESET}
""")


def run_interactive():
    """Run the interactive CLI session."""
    print_header()

    engine = ConversationEngine(model=os.environ.get("SIM_MODEL", "gemini-2.5-flash"))
    bridge = SimulationBridge()
    user_id = "cli_user"

    # Start the conversation
    response = engine.start_new(user_id, "")
    if not response or response.strip() == "":
        response = (
            "👋 Hey! I'm the Market Simulator — your thinking partner for "
            "validating product assumptions.\n\n"
            "Tell me about the product or idea you want to test. "
            "What are you building, and who is it for?"
        )
    print_agent(response)

    while True:
        try:
            user_input = input(f"\n{Colors.GREEN}{Colors.BOLD}You:{Colors.RESET} ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nGoodbye!")
            break

        if not user_input:
            continue

        # Handle CLI commands
        if user_input.lower() == "/quit":
            print("\nGoodbye!")
            break
        elif user_input.lower() == "/status":
            status = engine.get_status(user_id)
            print_status(status)
            continue
        elif user_input.lower() == "/cancel":
            result = engine.cancel(user_id)
            print_status(result)
            continue

        # Process the message through the conversation engine
        response = engine.handle_message(user_id, user_input)
        print_agent(response)

        # Check if the simulation should be launched
        session = engine.sessions.get(user_id)
        if session and session.stage == Stage.RUNNING:
            print_status("\n⏳ Running simulation... This may take 5-15 minutes.\n")

            config_json = engine.get_session_config(user_id)
            if not config_json:
                print_error("No simulation config found. Something went wrong.")
                engine.set_stage(user_id, Stage.IDLE)
                continue

            try:
                config = bridge.build_config(config_json)

                # Progress callback for CLI
                async def progress_callback(msg: str):
                    # Replace Slack emoji
                    msg = msg.replace(":earth_americas:", "🌎")
                    msg = msg.replace(":busts_in_silhouette:", "👥")
                    msg = msg.replace(":speech_balloon:", "💬")
                    msg = msg.replace(":bar_chart:", "📊")
                    msg = msg.replace(":tada:", "🎉")
                    msg = msg.replace(":white_check_mark:", "✅")
                    msg = msg.replace(":x:", "❌")
                    msg = msg.replace(":hourglass_flowing_sand:", "⏳")
                    msg = msg.replace(":rocket:", "🚀")
                    msg = msg.replace(":mag:", "🔍")
                    print_status(msg)

                # Run the simulation
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    results = loop.run_until_complete(
                        bridge.run_simulation(config, progress_callback)
                    )
                finally:
                    loop.close()

                if results.get("success"):
                    report_path = results.get("report_path")
                    if report_path and os.path.exists(report_path):
                        with open(report_path, "r") as f:
                            report = f.read()
                        print_agent(report[:5000])
                        if len(report) > 5000:
                            print_status(
                                f"\n... Report truncated. Full report saved to: {report_path}"
                            )
                        else:
                            print_status(f"\nFull report saved to: {report_path}")

                    print_status(
                        f"\n✅ Simulation complete! "
                        f"{results.get('interviews_count', 0)} interviews analyzed."
                        f"\nOutput directory: {results.get('output_dir', 'output')}"
                    )
                    engine.set_stage(user_id, Stage.COMPLETE)
                else:
                    error = results.get("error", "Unknown error")
                    print_error(f"Simulation failed: {error}")
                    engine.set_stage(user_id, Stage.IDLE)

            except Exception as e:
                print_error(f"Simulation crashed: {e}")
                engine.set_stage(user_id, Stage.IDLE)

            print(f"\n{Colors.DIM}Send another message to start a new simulation, or /quit to exit.{Colors.RESET}")


def run_from_config(config_path: str):
    """Run a simulation directly from a YAML config file (non-interactive)."""
    print_header()
    print_status(f"Loading config from: {config_path}")

    # Use the existing run.py pipeline for config-based runs
    from config import load_config
    config = load_config(config_path)

    bridge = SimulationBridge()

    async def progress_callback(msg: str):
        msg = msg.replace(":earth_americas:", "🌎")
        msg = msg.replace(":busts_in_silhouette:", "👥")
        msg = msg.replace(":speech_balloon:", "💬")
        msg = msg.replace(":bar_chart:", "📊")
        msg = msg.replace(":tada:", "🎉")
        msg = msg.replace(":white_check_mark:", "✅")
        msg = msg.replace(":x:", "❌")
        msg = msg.replace(":hourglass_flowing_sand:", "⏳")
        print_status(msg)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        results = loop.run_until_complete(
            bridge.run_simulation(config, progress_callback)
        )
    finally:
        loop.close()

    if results.get("success"):
        print_status(f"\n✅ Simulation complete! Output: {results.get('output_dir')}")
    else:
        print_error(f"\n❌ Simulation failed: {results.get('error')}")


def main():
    parser = argparse.ArgumentParser(
        description="Market Simulator — Interactive CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli/interactive.py                     # Start interactive session
  python cli/interactive.py --config config.yaml  # Run from config file
        """,
    )
    parser.add_argument(
        "--config", "-c",
        help="Path to a YAML config file (skips interactive flow)",
    )
    parser.add_argument(
        "--model", "-m",
        default=os.environ.get("SIM_MODEL", "gemini-2.5-flash"),
        help="LLM model to use (default: gemini-2.5-flash)",
    )
    args = parser.parse_args()

    if args.config:
        run_from_config(args.config)
    else:
        run_interactive()


if __name__ == "__main__":
    main()
