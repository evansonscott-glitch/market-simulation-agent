#!/usr/bin/env python3
"""
Market Simulator — Main Runner (Hardened)

Usage:
    python3 run.py path/to/config.yaml [--resume] [--log-level DEBUG]

This is the single entry point for running a simulation. It:
1. Validates and loads the YAML config
2. Ensures a world model exists (generates one if needed)
3. Generates the persona audience
4. Conducts interviews (with checkpointing for crash recovery)
5. Analyzes results
6. Produces the final report

Hardening improvements:
  - Proper structured logging throughout
  - Config validation with clear error messages
  - Crash recovery via checkpointing (--resume flag)
  - Graceful degradation at every stage
  - Memory management for large simulations
  - Clean error reporting
"""
import sys
import os
import json
import asyncio
import argparse
from datetime import datetime
from typing import List

# Ensure the package root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engines.logging_config import setup_logging, get_logger
from config import load_config, load_context_file, ConfigValidationError
from engines.research_engine import ensure_world_model
from engines.persona_engine import generate_personas
from engines.interview_engine import run_interviews, format_transcripts_markdown
from engines.analysis_engine import analyze_interviews
from engines.checkpoint import SimulationCheckpoint


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Market Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 run.py examples/revhawk/config.yaml
  python3 run.py examples/revhawk/config.yaml --resume
  python3 run.py examples/revhawk/config.yaml --log-level DEBUG
        """,
    )
    parser.add_argument("config", help="Path to the YAML config file")
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume a previously interrupted simulation from checkpoint",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="Force a fresh run, ignoring any existing checkpoint",
    )
    return parser.parse_args()


def run_simulation(config_path: str, resume: bool = False, fresh: bool = False, log_level: str = "INFO"):
    """
    Run the full simulation pipeline.

    Args:
        config_path: Path to the YAML config file.
        resume: Whether to resume from a previous checkpoint.
        fresh: Whether to force a fresh run (clear existing checkpoint).
        log_level: Logging level.

    Returns:
        Path to the output directory.
    """
    start_time = datetime.now()

    # ── Step 0: Initialize Logging ──
    # We set up a temporary logger first, then re-initialize with the output log file
    setup_logging(level=log_level)
    logger = get_logger("runner")

    logger.info("=" * 60)
    logger.info("  MARKET SIMULATOR")
    logger.info("=" * 60)

    # ── Step 1: Load & Validate Config ──
    logger.info("[1/6] Loading and validating config: %s", config_path)

    try:
        config = load_config(config_path)
    except FileNotFoundError as e:
        logger.error("Config file not found: %s", config_path)
        sys.exit(1)
    except ConfigValidationError as e:
        logger.error("Config validation failed:\n%s", e)
        sys.exit(1)
    except Exception as e:
        logger.error("Failed to load config: %s", e)
        sys.exit(1)

    logger.info("  Product: %s", config["product_name"])
    logger.info("  Target Market: %s", config["target_market"][:80])
    logger.info("  Persona Count: %d", config["persona_count"])
    logger.info("  Interview Turns: %d", config["interview_turns"])
    logger.info("  Interaction Context: %s", config["interaction_context"])
    logger.info("  LLM Model: %s", config["llm_model"])

    if config.get("assumptions"):
        logger.info("  Assumptions to test: %d", len(config["assumptions"]))
    if config.get("questions"):
        logger.info("  Questions to explore: %d", len(config["questions"]))

    # Create timestamped output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_name = f"sim_{config['product_name'].lower().replace(' ', '_')}_{timestamp}"
    output_dir = os.path.join(config["output_dir"], run_name)
    os.makedirs(output_dir, exist_ok=True)
    config["output_dir"] = output_dir

    # Re-initialize logging with output log file
    log_file = os.path.join(output_dir, "simulation.log")
    setup_logging(level=log_level, log_file=log_file)
    logger = get_logger("runner")
    logger.info("Output directory: %s", output_dir)
    logger.info("Log file: %s", log_file)

    # Initialize checkpoint
    checkpoint = SimulationCheckpoint(output_dir)
    if fresh and checkpoint.has_existing_run():
        logger.info("Fresh run requested — clearing existing checkpoint")
        checkpoint.clear()

    # ── Step 2: Ensure World Model ──
    logger.info("[2/6] Preparing world model...")
    try:
        world_model = ensure_world_model(config)
        if config.get("_generated_world_model"):
            config["world_model_path"] = os.path.join(output_dir, "generated_world_model.md")
    except Exception as e:
        logger.error("World model preparation failed: %s", e)
        logger.info("Continuing without world model — persona quality may be reduced")
        world_model = ""

    checkpoint.save_state(phase="world_model", progress="World model ready")

    # ── Step 3: Generate Personas ──
    logger.info("[3/6] Generating %d personas...", config["persona_count"])

    # Check if we can resume with existing personas
    personas = None
    if resume:
        personas = checkpoint.load_personas()
        if personas:
            logger.info("Resumed %d personas from checkpoint", len(personas))

    if not personas:
        try:
            personas = generate_personas(config)
        except ValueError as e:
            logger.error("Persona generation failed completely: %s", e)
            sys.exit(1)
        except Exception as e:
            logger.error("Unexpected error in persona generation: %s", e)
            sys.exit(1)

        # Save personas
        checkpoint.save_personas(personas)

    logger.info("  Generated %d personas", len(personas))

    # Save personas to output
    personas_path = os.path.join(output_dir, "personas.json")
    try:
        with open(personas_path, "w", encoding="utf-8") as f:
            json.dump(personas, f, indent=2, default=str)
    except IOError as e:
        logger.error("Failed to save personas: %s", e)

    # Save audience summary
    audience_summary = _build_audience_summary(personas)
    summary_path = os.path.join(output_dir, "audience_summary.md")
    try:
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(audience_summary)
    except IOError as e:
        logger.error("Failed to save audience summary: %s", e)

    checkpoint.save_state(
        phase="personas",
        progress=f"{len(personas)} personas generated",
    )

    # ── Step 4: Conduct Interviews ──
    logger.info(
        "[4/6] Conducting %d interviews (%d turns each)...",
        len(personas), config["interview_turns"],
    )

    try:
        interviews = asyncio.run(
            run_interviews(
                personas=personas,
                config=config,
                checkpoint=checkpoint if resume else checkpoint,  # Always use checkpoint for persistence
            )
        )
    except Exception as e:
        logger.error("Interview phase failed: %s", e)
        # Try to recover from checkpoint
        interviews = checkpoint.load_all_interviews()
        if interviews:
            logger.info("Recovered %d interviews from checkpoint", len(interviews))
        else:
            logger.error("No interviews could be recovered. Exiting.")
            sys.exit(1)

    logger.info("  Completed %d interviews", len(interviews))

    # Save transcripts
    try:
        transcripts_md = format_transcripts_markdown(interviews)
        transcripts_path = os.path.join(output_dir, "transcripts.md")
        with open(transcripts_path, "w", encoding="utf-8") as f:
            f.write(transcripts_md)
    except Exception as e:
        logger.error("Failed to save transcripts: %s", e)

    # Save raw interview data
    try:
        interviews_path = os.path.join(output_dir, "interviews.json")
        with open(interviews_path, "w", encoding="utf-8") as f:
            json.dump(interviews, f, indent=2, default=str)
    except Exception as e:
        logger.error("Failed to save raw interviews: %s", e)

    checkpoint.save_state(
        phase="interviews_saved",
        progress=f"{len(interviews)} interviews saved",
    )

    # ── Step 5: Analyze Results ──
    logger.info("[5/6] Analyzing interviews and generating report...")

    try:
        results = asyncio.run(analyze_interviews(interviews, config))
    except Exception as e:
        logger.error("Analysis failed: %s", e)
        results = {
            "report": f"# Analysis Failed\n\nThe analysis phase encountered an error: {e}\n\nRaw interview data has been saved.",
            "insights": [],
            "audience_stats": {"total_interviews": len(interviews)},
        }

    # Save report
    report_path = os.path.join(output_dir, "report.md")
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(results["report"])
    except IOError as e:
        logger.error("Failed to save report: %s", e)

    # Save raw insights
    try:
        insights_path = os.path.join(output_dir, "insights.json")
        with open(insights_path, "w", encoding="utf-8") as f:
            json.dump(results["insights"], f, indent=2, default=str)
    except IOError as e:
        logger.error("Failed to save insights: %s", e)

    # Save quantitative summary
    try:
        quant_path = os.path.join(output_dir, "quantitative_summary.json")
        with open(quant_path, "w", encoding="utf-8") as f:
            json.dump(results["audience_stats"], f, indent=2, default=str)
    except IOError as e:
        logger.error("Failed to save quantitative summary: %s", e)

    # ── Step 6: Save Run Metadata ──
    logger.info("[6/6] Saving run metadata...")

    elapsed = (datetime.now() - start_time).total_seconds()

    config_snapshot = {k: v for k, v in config.items() if not k.startswith("_")}
    config_snapshot["archetypes"] = {k: v["name"] for k, v in config["archetypes"].items()}
    config_snapshot["run_timestamp"] = timestamp
    config_snapshot["personas_generated"] = len(personas)
    config_snapshot["interviews_completed"] = len(interviews)
    config_snapshot["elapsed_seconds"] = round(elapsed, 1),
    config_snapshot["log_level"] = log_level

    try:
        meta_path = os.path.join(output_dir, "run_metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(config_snapshot, f, indent=2, default=str)
    except IOError as e:
        logger.error("Failed to save run metadata: %s", e)

    # Mark checkpoint as complete
    checkpoint.mark_complete()

    # ── Done ──
    logger.info("=" * 60)
    logger.info("  SIMULATION COMPLETE")
    logger.info("  Time: %.0f seconds (%.1f minutes)", elapsed, elapsed / 60)
    logger.info("  Output: %s", output_dir)
    logger.info("  Report: %s", report_path)
    logger.info("  Log: %s", log_file)
    logger.info("=" * 60)

    return output_dir


def _build_audience_summary(personas: List) -> str:
    """Build a Markdown summary of the generated audience."""
    if not personas:
        return "# Audience Summary\n\n**No personas generated.**\n"

    lines = ["# Audience Summary\n"]
    lines.append(f"**Total Personas:** {len(personas)}\n")

    # Archetype distribution
    archetypes = {}
    for p in personas:
        a = p.get("archetype_name", "Unknown")
        archetypes[a] = archetypes.get(a, 0) + 1
    lines.append("## Archetype Distribution")
    for a, count in sorted(archetypes.items(), key=lambda x: -x[1]):
        lines.append(f"- {a}: {count} ({count / len(personas) * 100:.0f}%)")

    # Disposition distribution
    dispositions = {}
    for p in personas:
        d = p.get("disposition", "unknown")
        dispositions[d] = dispositions.get(d, 0) + 1
    lines.append("\n## Disposition Distribution")
    for d, count in sorted(dispositions.items(), key=lambda x: -x[1]):
        lines.append(f"- {d}: {count} ({count / len(personas) * 100:.0f}%)")

    # Industry distribution
    industries = {}
    for p in personas:
        ind = p.get("industry", "Unknown")
        industries[ind] = industries.get(ind, 0) + 1
    lines.append("\n## Industry Distribution")
    for ind, count in sorted(industries.items(), key=lambda x: -x[1])[:15]:
        lines.append(f"- {ind}: {count} ({count / len(personas) * 100:.0f}%)")
    if len(industries) > 15:
        lines.append(f"- ... and {len(industries) - 15} more")

    # Skepticism stats
    scores = [p.get("skepticism_score", 5) for p in personas]
    avg = sum(scores) / len(scores)
    lines.append(f"\n## Skepticism")
    lines.append(f"- Average: {avg:.1f}/10")
    lines.append(f"- Range: {min(scores)} - {max(scores)}")
    high_skepticism = sum(1 for s in scores if s >= 7)
    lines.append(f"- High skepticism (7+): {high_skepticism} ({high_skepticism / len(personas) * 100:.0f}%)")

    return "\n".join(lines)


if __name__ == "__main__":
    args = parse_args()

    if not os.path.exists(args.config):
        print(f"Error: Config file not found: {args.config}")
        sys.exit(1)

    try:
        run_simulation(
            config_path=args.config,
            resume=args.resume,
            fresh=args.fresh,
            log_level=args.log_level,
        )
    except KeyboardInterrupt:
        print("\nSimulation interrupted by user. Progress has been checkpointed.")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        print(f"\nFatal error: {e}")
        sys.exit(1)
