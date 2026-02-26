#!/usr/bin/env python3
"""
Philo Ventures Market Simulator — Main Runner

Usage:
    python3 run.py path/to/config.yaml

This is the single entry point for running a simulation. It:
1. Loads the YAML config
2. Ensures a world model exists (generates one if needed)
3. Generates the persona audience
4. Conducts interviews
5. Analyzes results
6. Produces the final report

All output is saved to the output directory specified in the config.
"""
import sys
import os
import json
import asyncio
from datetime import datetime

# Ensure the package root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config, load_context_file
from engines.research_engine import ensure_world_model
from engines.persona_engine import generate_personas
from engines.interview_engine import run_interviews, format_transcripts_markdown
from engines.analysis_engine import analyze_interviews


def run_simulation(config_path: str):
    """Run the full simulation pipeline."""
    start_time = datetime.now()
    print("=" * 60)
    print("  PHILO VENTURES MARKET SIMULATOR")
    print("=" * 60)

    # ── Step 1: Load Config ──
    print(f"\n[1/6] Loading config from: {config_path}")
    config = load_config(config_path)
    print(f"  Product: {config['product_name']}")
    print(f"  Target Market: {config['target_market']}")
    print(f"  Persona Count: {config['persona_count']}")
    print(f"  Interview Turns: {config['interview_turns']}")
    print(f"  Interaction Context: {config['interaction_context']}")
    print(f"  LLM Model: {config['llm_model']}")

    if config.get("assumptions"):
        print(f"  Assumptions to test: {len(config['assumptions'])}")
    if config.get("questions"):
        print(f"  Questions to explore: {len(config['questions'])}")

    # Create timestamped output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_name = f"sim_{config['product_name'].lower().replace(' ', '_')}_{timestamp}"
    output_dir = os.path.join(config["output_dir"], run_name)
    os.makedirs(output_dir, exist_ok=True)
    config["output_dir"] = output_dir
    print(f"  Output: {output_dir}")

    # ── Step 2: Ensure World Model ──
    print(f"\n[2/6] Preparing world model...")
    world_model = ensure_world_model(config)

    # If world model was generated (not from file), update the config path
    if config.get("_generated_world_model"):
        config["world_model_path"] = os.path.join(output_dir, "generated_world_model.md")

    # ── Step 3: Generate Personas ──
    print(f"\n[3/6] Generating {config['persona_count']} personas...")
    personas = generate_personas(config)
    print(f"  Generated {len(personas)} personas")

    # Save personas
    personas_path = os.path.join(output_dir, "personas.json")
    with open(personas_path, "w") as f:
        json.dump(personas, f, indent=2, default=str)

    # Save audience summary
    audience_summary = _build_audience_summary(personas)
    summary_path = os.path.join(output_dir, "audience_summary.md")
    with open(summary_path, "w") as f:
        f.write(audience_summary)

    # ── Step 4: Conduct Interviews ──
    print(f"\n[4/6] Conducting {len(personas)} interviews ({config['interview_turns']} turns each)...")
    interviews = asyncio.run(run_interviews(personas, config))
    print(f"  Completed {len(interviews)} interviews")

    # Save transcripts
    transcripts_md = format_transcripts_markdown(interviews)
    transcripts_path = os.path.join(output_dir, "transcripts.md")
    with open(transcripts_path, "w") as f:
        f.write(transcripts_md)

    # Save raw interview data
    interviews_path = os.path.join(output_dir, "interviews.json")
    with open(interviews_path, "w") as f:
        json.dump(interviews, f, indent=2, default=str)

    # ── Step 5: Analyze Results ──
    print(f"\n[5/6] Analyzing interviews and generating report...")
    results = asyncio.run(analyze_interviews(interviews, config))

    # Save report
    report_path = os.path.join(output_dir, "report.md")
    with open(report_path, "w") as f:
        f.write(results["report"])

    # Save raw insights
    insights_path = os.path.join(output_dir, "insights.json")
    with open(insights_path, "w") as f:
        json.dump(results["insights"], f, indent=2, default=str)

    # ── Step 6: Save Config Snapshot ──
    print(f"\n[6/6] Saving run metadata...")
    config_snapshot = {k: v for k, v in config.items() if not k.startswith("_")}
    config_snapshot["archetypes"] = {k: v["name"] for k, v in config["archetypes"].items()}
    config_snapshot["run_timestamp"] = timestamp
    config_snapshot["personas_generated"] = len(personas)
    config_snapshot["interviews_completed"] = len(interviews)

    meta_path = os.path.join(output_dir, "run_metadata.json")
    with open(meta_path, "w") as f:
        json.dump(config_snapshot, f, indent=2, default=str)

    # ── Done ──
    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n{'=' * 60}")
    print(f"  SIMULATION COMPLETE")
    print(f"  Time: {elapsed:.0f} seconds ({elapsed/60:.1f} minutes)")
    print(f"  Output: {output_dir}")
    print(f"  Report: {report_path}")
    print(f"  Transcripts: {transcripts_path}")
    print(f"{'=' * 60}")

    return output_dir


def _build_audience_summary(personas: List) -> str:
    """Build a Markdown summary of the generated audience."""
    lines = ["# Audience Summary\n"]
    lines.append(f"**Total Personas:** {len(personas)}\n")

    # Archetype distribution
    archetypes = {}
    for p in personas:
        a = p.get("archetype_name", "Unknown")
        archetypes[a] = archetypes.get(a, 0) + 1
    lines.append("## Archetype Distribution")
    for a, count in sorted(archetypes.items(), key=lambda x: -x[1]):
        lines.append(f"- {a}: {count} ({count/len(personas)*100:.0f}%)")

    # Disposition distribution
    dispositions = {}
    for p in personas:
        d = p.get("disposition", "unknown")
        dispositions[d] = dispositions.get(d, 0) + 1
    lines.append("\n## Disposition Distribution")
    for d, count in sorted(dispositions.items(), key=lambda x: -x[1]):
        lines.append(f"- {d}: {count} ({count/len(personas)*100:.0f}%)")

    # Industry distribution
    industries = {}
    for p in personas:
        ind = p.get("industry", "Unknown")
        industries[ind] = industries.get(ind, 0) + 1
    lines.append("\n## Industry Distribution")
    for ind, count in sorted(industries.items(), key=lambda x: -x[1]):
        lines.append(f"- {ind}: {count} ({count/len(personas)*100:.0f}%)")

    # Skepticism stats
    scores = [p.get("skepticism_score", 5) for p in personas]
    avg = sum(scores) / max(len(scores), 1)
    lines.append(f"\n## Skepticism")
    lines.append(f"- Average: {avg:.1f}/10")
    lines.append(f"- Range: {min(scores)} - {max(scores)}")
    lines.append(f"- High skepticism (7+): {sum(1 for s in scores if s >= 7)} ({sum(1 for s in scores if s >= 7)/len(personas)*100:.0f}%)")

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 run.py path/to/config.yaml")
        print("\nExample: python3 run.py examples/revhawk/config.yaml")
        sys.exit(1)

    config_path = sys.argv[1]
    if not os.path.exists(config_path):
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    run_simulation(config_path)
