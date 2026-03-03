"""
Market Simulator — Simulation Runner (Slack Bot Bridge)

Bridges the conversational config from the Slack bot to the actual
simulation engine. Takes a dict config (from the conversation), writes
a proper YAML config, generates a world model, and runs the simulation.
"""
import os
import sys
import json
import yaml
import asyncio
import tempfile
from datetime import datetime
from typing import Dict, Any, Callable, Optional

# Add parent directory to path for simulation engine imports
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from engines.logging_config import setup_logging, get_logger
from config import load_config, ConfigValidationError
from engines.research_engine import ensure_world_model
from engines.persona_engine import generate_personas
from engines.interview_engine import run_interviews, format_transcripts_markdown
from engines.analysis_engine import analyze_interviews
from engines.checkpoint import SimulationCheckpoint

logger = get_logger("sim_runner")


def run_simulation_from_config(
    config: Dict[str, Any],
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Run a full simulation from a conversational config dict.

    Args:
        config: The simulation config dict from the conversation.
        progress_callback: Optional callback to post progress updates to Slack.

    Returns:
        Dict with 'report', 'insights', 'output_dir' keys.
    """
    setup_logging(level="INFO")

    def notify(msg: str):
        logger.info(msg)
        if progress_callback:
            try:
                progress_callback(msg)
            except Exception as e:
                logger.error("Progress callback failed: %s", e)

    # ── Step 1: Build the YAML config ──
    notify(":gear: *Step 1/5:* Building simulation config...")

    yaml_config = _build_yaml_config(config)

    # Write to a temp file so the existing config loader can validate it
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    product_slug = config.get("product_name", "simulation").lower().replace(" ", "_")[:30]
    run_name = f"sim_{product_slug}_{timestamp}"

    output_base = os.path.join(REPO_ROOT, "output", "slack_runs")
    output_dir = os.path.join(output_base, run_name)
    os.makedirs(output_dir, exist_ok=True)

    config_path = os.path.join(output_dir, "config.yaml")
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(yaml_config, f, default_flow_style=False, allow_unicode=True)

    # Load and validate through the standard config loader
    try:
        validated_config = load_config(config_path)
    except ConfigValidationError as e:
        raise ValueError(f"Config validation failed: {e}")

    validated_config["output_dir"] = output_dir

    # Set up logging to file
    log_file = os.path.join(output_dir, "simulation.log")
    setup_logging(level="INFO", log_file=log_file)

    checkpoint = SimulationCheckpoint(output_dir)

    # ── Step 2: Generate World Model ──
    notify(":earth_americas: *Step 2/5:* Researching market and building world model...")

    try:
        world_model = ensure_world_model(validated_config)
    except Exception as e:
        logger.error("World model generation failed: %s", e)
        notify(":warning: World model generation had issues — continuing with reduced context.")
        world_model = ""

    checkpoint.save_state(phase="world_model", progress="World model ready")

    # ── Step 3: Generate Personas ──
    persona_count = validated_config.get("persona_count", 30)
    notify(f":busts_in_silhouette: *Step 3/5:* Generating {persona_count} personas...")

    try:
        personas = generate_personas(validated_config)
    except Exception as e:
        raise RuntimeError(f"Persona generation failed: {e}")

    checkpoint.save_personas(personas)
    notify(f":white_check_mark: Generated {len(personas)} personas across {_count_archetypes(personas)} archetypes.")

    # Save personas
    personas_path = os.path.join(output_dir, "personas.json")
    with open(personas_path, "w", encoding="utf-8") as f:
        json.dump(personas, f, indent=2, default=str)

    # Save audience summary
    audience_summary = _build_audience_summary(personas)
    summary_path = os.path.join(output_dir, "audience_summary.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(audience_summary)

    checkpoint.save_state(phase="personas", progress=f"{len(personas)} personas generated")

    # ── Step 4: Run Interviews ──
    turns = validated_config.get("interview_turns", 6)
    notify(f":speech_balloon: *Step 4/5:* Running {len(personas)} interviews ({turns} turns each)... This is the longest step.")

    try:
        interviews = asyncio.run(
            run_interviews(
                personas=personas,
                config=validated_config,
                checkpoint=checkpoint,
            )
        )
    except Exception as e:
        # Try to recover from checkpoint
        interviews = checkpoint.load_all_interviews()
        if interviews:
            notify(f":warning: Some interviews failed, but recovered {len(interviews)} from checkpoint.")
        else:
            raise RuntimeError(f"Interview phase failed completely: {e}")

    notify(f":white_check_mark: Completed {len(interviews)} interviews.")

    # Save transcripts
    try:
        transcripts_md = format_transcripts_markdown(interviews)
        transcripts_path = os.path.join(output_dir, "transcripts.md")
        with open(transcripts_path, "w", encoding="utf-8") as f:
            f.write(transcripts_md)
    except Exception as e:
        logger.error("Failed to save transcripts: %s", e)

    # Save raw interviews
    interviews_path = os.path.join(output_dir, "interviews.json")
    with open(interviews_path, "w", encoding="utf-8") as f:
        json.dump(interviews, f, indent=2, default=str)

    checkpoint.save_state(phase="interviews_saved", progress=f"{len(interviews)} interviews saved")

    # ── Step 5: Analyze Results ──
    notify(":bar_chart: *Step 5/5:* Analyzing results and generating report...")

    try:
        results = asyncio.run(analyze_interviews(interviews, validated_config))
    except Exception as e:
        logger.error("Analysis failed: %s", e)
        results = {
            "report": f"# Analysis Failed\n\nError: {e}\n\nRaw interview data has been saved to {output_dir}.",
            "insights": [],
            "audience_stats": {"total_interviews": len(interviews)},
        }

    # Save report
    report_path = os.path.join(output_dir, "report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(results["report"])

    # Save insights
    insights_path = os.path.join(output_dir, "insights.json")
    with open(insights_path, "w", encoding="utf-8") as f:
        json.dump(results["insights"], f, indent=2, default=str)

    # Save quantitative summary
    quant_path = os.path.join(output_dir, "quantitative_summary.json")
    with open(quant_path, "w", encoding="utf-8") as f:
        json.dump(results["audience_stats"], f, indent=2, default=str)

    # Save run metadata
    meta = {
        "product_name": validated_config.get("product_name", "Unknown"),
        "persona_count": len(personas),
        "interviews_completed": len(interviews),
        "timestamp": timestamp,
        "output_dir": output_dir,
    }
    meta_path = os.path.join(output_dir, "run_metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, default=str)

    checkpoint.mark_complete()

    return {
        "report": results["report"],
        "insights": results.get("insights", {}),
        "audience_stats": results.get("audience_stats", {}),
        "output_dir": output_dir,
    }


def _build_yaml_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the conversational config dict into a proper YAML config structure."""
    yaml_config = {
        "product": {
            "name": config.get("product_name", "Unknown Product"),
            "description": config.get("product_description", "No description provided."),
            "target_market": config.get("target_market", "No target market specified."),
        },
        "assumptions": config.get("assumptions", []),
        "questions": config.get("questions", []),
        "archetypes": {},
        "settings": {
            "persona_count": config.get("persona_count", 30),
            "interview_turns": config.get("interview_turns", 6),
            "interaction_context": "warm_demo",
            "llm_model": "gemini-2.5-flash",
            "persona_concurrency": 5,
            "interview_concurrency": 10,
        },
        "context": {},
        "output_dir": "output",
    }

    # Build archetypes
    archetypes = config.get("archetypes", {})
    if isinstance(archetypes, dict):
        for key, value in archetypes.items():
            if isinstance(value, dict):
                yaml_config["archetypes"][key] = {
                    "name": value.get("name", key),
                    "description": value.get("description", f"A {key} persona."),
                    "percentage": value.get("percentage", 100 // max(len(archetypes), 1)),
                }

    # If no archetypes provided, use sensible defaults
    if not yaml_config["archetypes"]:
        yaml_config["archetypes"] = {
            "target_user": {
                "name": "Target User",
                "description": "A typical member of the target market who would use this product.",
                "percentage": 30,
            },
            "budget_holder": {
                "name": "Budget Holder / Decision Maker",
                "description": "A senior leader who would approve the purchase. Focused on ROI and risk.",
                "percentage": 20,
            },
            "power_user": {
                "name": "Power User / Early Adopter",
                "description": "A tech-savvy user who actively seeks better tools. Willing to try new things but has high standards.",
                "percentage": 20,
            },
            "skeptic": {
                "name": "Skeptic / Resistant Buyer",
                "description": "Someone who is satisfied with their current workflow and resistant to change. Hard to convince.",
                "percentage": 15,
            },
            "red_team": {
                "name": "Red Team Critic",
                "description": "A deliberately critical persona who will challenge every aspect of the value proposition. Represents the hardest buyers.",
                "percentage": 15,
            },
        }

    return yaml_config


def _count_archetypes(personas: list) -> int:
    """Count unique archetypes in the persona list."""
    return len(set(p.get("archetype_name", "Unknown") for p in personas))


def _build_audience_summary(personas: list) -> str:
    """Build a Markdown summary of the generated audience."""
    if not personas:
        return "# Audience Summary\n\n**No personas generated.**\n"

    lines = ["# Audience Summary\n"]
    lines.append(f"**Total Personas:** {len(personas)}\n")

    archetypes = {}
    for p in personas:
        a = p.get("archetype_name", "Unknown")
        archetypes[a] = archetypes.get(a, 0) + 1
    lines.append("## Archetype Distribution")
    for a, count in sorted(archetypes.items(), key=lambda x: -x[1]):
        lines.append(f"- {a}: {count} ({count / len(personas) * 100:.0f}%)")

    return "\n".join(lines)
