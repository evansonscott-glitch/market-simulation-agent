"""
Integration Test: v2 Pipeline (RAG + Census + Scoring)

Runs the upgraded pipeline on the Refinery example config with a small
sample (10 personas, 4 turns) to verify all three new engines work
together end-to-end.

Usage:
    cd /home/ubuntu/msa-consolidate
    python3 test_v2_pipeline.py
"""
import asyncio
import json
import os
import sys
import time
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_v2")

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config
from engines.research_engine_v2 import generate_world_model_v2
from engines.market_census import build_census
from engines.persona_engine import generate_personas
from engines.interview_engine import run_interviews
from engines.analysis_engine import analyze_interviews
from engines.scoring_engine import score_simulation_batch, generate_score_report


async def main():
    start_time = time.time()
    
    # ── Load config ──
    config_path = os.path.join(os.path.dirname(__file__), "examples", "refinery", "config.yaml")
    logger.info("Loading config from: %s", config_path)
    config = load_config(config_path)
    
    # Override for a faster test run
    config["persona_count"] = 10
    config["interview_turns"] = 4
    config["persona_concurrency"] = 5
    config["interview_concurrency"] = 5
    
    # Set output dir for this test
    output_dir = os.path.join(os.path.dirname(__file__), "test_v2_output")
    os.makedirs(output_dir, exist_ok=True)
    config["output_dir"] = output_dir
    
    # ══════════════════════════════════════════
    # STEP 1: RAG World Model (Fix #1)
    # ══════════════════════════════════════════
    logger.info("=" * 60)
    logger.info("STEP 1: Generating RAG-based world model...")
    logger.info("=" * 60)
    
    # Force RAG pipeline (ignore any existing world model file)
    config["world_model_path"] = None
    world_model = generate_world_model_v2(config)
    
    # Save for comparison
    wm_path = os.path.join(output_dir, "world_model_v2.md")
    with open(wm_path, "w") as f:
        f.write(world_model)
    logger.info("World model saved: %s (%d chars)", wm_path, len(world_model))
    
    # ══════════════════════════════════════════
    # STEP 2: Market Census (Fix #2)
    # ══════════════════════════════════════════
    logger.info("=" * 60)
    logger.info("STEP 2: Building market census and persona briefs...")
    logger.info("=" * 60)
    
    census, persona_briefs = build_census(config, world_model)
    
    logger.info("Census variables: %d", len(census.get("variables", [])))
    logger.info("Persona briefs: %d", len(persona_briefs))
    
    # ══════════════════════════════════════════
    # STEP 3: Generate Personas (using briefs)
    # ══════════════════════════════════════════
    logger.info("=" * 60)
    logger.info("STEP 3: Generating personas (informed by census briefs)...")
    logger.info("=" * 60)
    
    # Inject census briefs into the world model so persona engine uses them
    brief_text = "\n\n## Census-Based Persona Briefs\n\n"
    brief_text += "Each persona should match these pre-assigned attributes:\n\n"
    for brief in persona_briefs:
        attrs = {k: v for k, v in brief.items() if k not in ("persona_index",)}
        brief_text += f"- Persona {brief['persona_index']}: {json.dumps(attrs)}\n"
    
    enriched_world_model = world_model + brief_text
    config["_generated_world_model"] = enriched_world_model
    personas = generate_personas(config)
    logger.info("Generated %d personas", len(personas))
    
    # ══════════════════════════════════════════
    # STEP 4: Run Interviews
    # ══════════════════════════════════════════
    logger.info("=" * 60)
    logger.info("STEP 4: Running interviews (%d personas, %d turns each)...",
                len(personas), config["interview_turns"])
    logger.info("=" * 60)
    
    interviews = await run_interviews(personas, config)
    successful = [i for i in interviews if i]
    logger.info("Completed %d/%d interviews", len(successful), len(personas))
    
    # ══════════════════════════════════════════
    # STEP 5: Standard Analysis
    # ══════════════════════════════════════════
    logger.info("=" * 60)
    logger.info("STEP 5: Running standard analysis...")
    logger.info("=" * 60)
    
    analysis = await analyze_interviews(interviews, config)
    
    # Save report
    if analysis.get("report"):
        report_path = os.path.join(output_dir, "report.md")
        with open(report_path, "w") as f:
            f.write(analysis["report"])
        logger.info("Standard report saved: %s", report_path)
    
    # Save insights
    if analysis.get("insights"):
        insights_path = os.path.join(output_dir, "insights.json")
        with open(insights_path, "w") as f:
            json.dump(analysis["insights"], f, indent=2, default=str)
        logger.info("Insights saved: %s", insights_path)
    
    # ══════════════════════════════════════════
    # STEP 6: Objective Scoring (Fix #3)
    # ══════════════════════════════════════════
    logger.info("=" * 60)
    logger.info("STEP 6: Running objective scoring engine...")
    logger.info("=" * 60)
    
    scoring_result = score_simulation_batch(
        interviews=successful,
        model=config["llm_model"],
    )
    
    # Generate and save scoring report
    score_report_path = generate_score_report(scoring_result, output_dir)
    logger.info("Scoring report saved: %s", score_report_path)
    
    # ══════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════
    elapsed = time.time() - start_time
    
    logger.info("=" * 60)
    logger.info("V2 PIPELINE TEST COMPLETE")
    logger.info("=" * 60)
    logger.info("Total time: %.1f minutes", elapsed / 60)
    logger.info("Output directory: %s", output_dir)
    logger.info("")
    
    agg = scoring_result.get("aggregates", {})
    logger.info("── Scoring Summary ──")
    logger.info("Composite Score (avg): %.3f", agg.get("composite_score_avg", 0))
    logger.info("Conversion Rate: %.1f%%", agg.get("conversion_rate", 0) * 100)
    logger.info("")
    
    for dim, stats in agg.get("dimension_averages", {}).items():
        logger.info("  %s: %.3f (min=%.3f, max=%.3f)",
                    dim.replace("_", " ").title(), stats["avg"], stats["min"], stats["max"])
    
    logger.info("")
    logger.info("── Output Files ──")
    for fname in sorted(os.listdir(output_dir)):
        fpath = os.path.join(output_dir, fname)
        if os.path.isfile(fpath):
            size = os.path.getsize(fpath)
            logger.info("  %s (%s)", fname, _human_size(size))


def _human_size(size_bytes):
    """Convert bytes to human-readable size."""
    for unit in ["B", "KB", "MB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.0f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} GB"


if __name__ == "__main__":
    asyncio.run(main())
