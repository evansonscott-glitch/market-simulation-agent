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
from engines.context_quality import compute_context_quality
from engines.statistical_validation import (
    check_sample_adequacy,
    recommend_sample_size,
    generate_statistical_appendix,
)
from engines.bias_detection import run_bias_audit, generate_bias_audit_section
from engines.experiment_formats import validate_experiment_format, generate_format_section


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


def _check_api_key(model: str):
    """Check that the required API key is set for standalone pipeline mode."""
    if model.startswith("claude-"):
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            print("\n" + "=" * 70)
            print("  ANTHROPIC_API_KEY not set")
            print("=" * 70)
            print()
            print("  The standalone pipeline needs an API key to make LLM calls.")
            print()
            print("  For Claude models (default):")
            print("    export ANTHROPIC_API_KEY='your-key-here'")
            print()
            print("  Using Claude Code instead? No API key needed!")
            print("  Open this repo in Claude Code and say:")
            print("    'I want to run a market simulation'")
            print("  Claude Code will handle the LLM work directly.")
            print()
            print("=" * 70 + "\n")
            sys.exit(1)
    else:
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            print("\n" + "=" * 70)
            print(f"  OPENAI_API_KEY not set (required for model: {model})")
            print("=" * 70)
            print()
            print("  Set your API key:")
            print("    export OPENAI_API_KEY='your-key-here'")
            print()
            print("  Or switch to Claude (no key needed in Claude Code):")
            print("    Set llm_model: 'claude-sonnet-4-6' in your config")
            print()
            print("=" * 70 + "\n")
            sys.exit(1)


def run_simulation(config_path: str, resume: bool = False, fresh: bool = False, log_level: str = "INFO"):
    """
    Run the full simulation pipeline (standalone mode — requires API key).

    For Claude Code users: use the /user-simulation skill instead.
    Claude Code handles LLM work directly — no API key needed.

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

    # Check API key before proceeding
    _check_api_key(config["llm_model"])

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

    # ── Validate experiment format ──
    experiment_format = config.get("experiment_format", "interview")
    format_validation = validate_experiment_format(experiment_format, config)
    if not format_validation["valid"]:
        logger.error("Experiment format error: %s", format_validation["error"])
        sys.exit(1)
    for w in format_validation.get("warnings", []):
        logger.warning("Format: %s", w)

    # Inject format-specific interviewer prompt extension
    config["format_prompt_extension"] = format_validation.get("interviewer_prompt_extension", "")

    # Extract web content if a URL is provided for web-based formats
    config["extracted_content"] = ""
    url_fields = {
        "webpage_review": "webpage_url",
        "form_test": "form_url",
        "document_review": "document_url",
    }
    url_field = url_fields.get(experiment_format)
    if url_field and config.get(url_field):
        try:
            from engines.web_extraction import (
                extract_webpage, extract_form,
                format_webpage_for_prompt, format_form_for_prompt,
            )
            target_url = config[url_field]
            logger.info("Extracting content from: %s", target_url)
            if experiment_format == "form_test":
                extraction = extract_form(target_url)
                config["extracted_content"] = format_form_for_prompt(extraction)
            else:
                extraction = extract_webpage(target_url)
                config["extracted_content"] = format_webpage_for_prompt(extraction)
            logger.info("Web content extracted (%d chars)", len(config["extracted_content"]))
        except Exception as e:
            logger.warning("Web extraction failed: %s. Falling back to description.", str(e)[:200])

    # Fall back to manual descriptions if no URL extraction
    if not config["extracted_content"]:
        for desc_field in ("webpage_description", "document_description", "form_steps"):
            if config.get(desc_field):
                config["extracted_content"] = config[desc_field]
                break

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

    # ── Context Quality Assessment ──
    context_quality = compute_context_quality(config)
    logger.info("Context quality grade: %s", context_quality["grade"])
    for w in context_quality.get("warnings", []):
        logger.warning("Context: %s", w)

    # ── Sample Size Guidance ──
    num_segments = len(config.get("archetypes", {}))
    sample_rec = recommend_sample_size(num_segments)
    if config["persona_count"] < sample_rec["directional_total"]:
        logger.warning(
            "Sample size (%d) is below the recommended minimum (%d) for %d segments. "
            "Consider increasing persona_count for more reliable results.",
            config["persona_count"],
            sample_rec["directional_total"],
            num_segments,
        )

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

    # Check sample adequacy per segment
    archetype_counts = {}
    for p in personas:
        a = p.get("archetype_name", "unknown")
        archetype_counts[a] = archetype_counts.get(a, 0) + 1
    adequacy = check_sample_adequacy(len(personas), archetype_counts)
    if adequacy["adequacy"] == "underpowered":
        logger.warning("Sample adequacy: %s", adequacy["summary"])
    for w in adequacy.get("warnings", []):
        logger.warning("Sample: %s", w)

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
                checkpoint=checkpoint,
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

    # ── Run Bias Audit ──
    logger.info("Running bias audit...")
    bias_audit = run_bias_audit(interviews)
    logger.info("Bias risk: %s", bias_audit["overall_risk"])

    # ── Generate Statistical Appendix ──
    stat_appendix = generate_statistical_appendix(
        audience_stats=results.get("audience_stats", {}),
        config=config,
        context_quality=context_quality,
    )

    # ── Generate Format-Specific Section ──
    format_section = generate_format_section(experiment_format)

    # ── Enrich Report with Quality, Bias, and Statistical Sections ──
    enriched_report = results["report"]
    enriched_report += "\n\n---\n\n"
    if format_section:
        enriched_report += format_section + "\n\n"
    enriched_report += generate_bias_audit_section(bias_audit) + "\n\n"
    enriched_report += stat_appendix + "\n"

    # Save report
    report_path = os.path.join(output_dir, "report.md")
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(enriched_report)
    except IOError as e:
        logger.error("Failed to save report: %s", e)

    # Save bias audit data
    try:
        bias_path = os.path.join(output_dir, "bias_audit.json")
        with open(bias_path, "w", encoding="utf-8") as f:
            json.dump(bias_audit, f, indent=2, default=str)
    except IOError as e:
        logger.error("Failed to save bias audit: %s", e)

    # Save context quality data
    try:
        ctx_path = os.path.join(output_dir, "context_quality.json")
        with open(ctx_path, "w", encoding="utf-8") as f:
            json.dump(context_quality, f, indent=2, default=str)
    except IOError as e:
        logger.error("Failed to save context quality: %s", e)

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
    config_snapshot["elapsed_seconds"] = round(elapsed, 1)
    config_snapshot["log_level"] = log_level
    config_snapshot["context_quality_grade"] = context_quality.get("grade", "?")
    config_snapshot["bias_risk"] = bias_audit.get("overall_risk", "unknown")
    config_snapshot["experiment_format"] = experiment_format
    config_snapshot["sample_adequacy"] = adequacy.get("adequacy", "unknown")

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
