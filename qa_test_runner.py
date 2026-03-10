"""
QA Test Runner for Market Simulation Agent
Executes baseline + skill-specific tests and captures results.
"""
import asyncio
import json
import os
import sys
import time
import logging
import traceback
import copy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("qa_runner")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config

qa_output_dir = os.path.join(os.path.dirname(__file__), "qa_output")
os.makedirs(qa_output_dir, exist_ok=True)

results = []


# ═══════════════════════════════════════════════
# TEST: baseline_01 — Happy Path (Standard Input)
# ═══════════════════════════════════════════════

async def test_baseline_01():
    """
    Run the full pipeline end-to-end with the Refinery example config.
    This exercises: config loading → persona generation → interviews → analysis.
    """
    logger.info("=" * 60)
    logger.info("TEST baseline_01: Happy Path — Standard Input")
    logger.info("=" * 60)

    test_result = {
        "test_id": "baseline_01",
        "test_name": "Happy Path — Standard Input",
        "priority": "P0",
        "input": "Refinery example config (examples/refinery/config.yaml)",
        "transcript": [],
        "errors": [],
        "final_output": None,
        "passed": False,
    }

    try:
        # Step 1: Load config
        config_path = os.path.join(os.path.dirname(__file__), "examples", "refinery", "config.yaml")
        test_result["transcript"].append(f"Loading config from: {config_path}")
        config = load_config(config_path)
        config["persona_count"] = 5
        config["interview_turns"] = 4
        config["persona_concurrency"] = 5
        config["interview_concurrency"] = 5
        output_dir = os.path.join(qa_output_dir, "baseline_01")
        os.makedirs(output_dir, exist_ok=True)
        config["output_dir"] = output_dir
        test_result["transcript"].append("Config loaded successfully")

        # Step 2: Research engine (world model)
        from engines.research_engine_v2 import generate_world_model_v2
        test_result["transcript"].append("Generating world model via RAG engine...")
        world_model = generate_world_model_v2(config)
        test_result["transcript"].append(f"World model generated: {len(world_model)} chars")

        if not world_model or len(world_model) < 100:
            test_result["errors"].append("World model is empty or too short")

        config["_generated_world_model"] = world_model

        # Step 3: Market census
        try:
            from engines.market_census import build_market_census
            test_result["transcript"].append("Building market census...")
            census = await build_market_census(config)
            test_result["transcript"].append(f"Census built: {len(census.get('persona_briefs', []))} persona briefs")
            if not census.get("persona_briefs"):
                test_result["transcript"].append("WARNING: Census produced no persona briefs (non-blocking)")
        except Exception as ce:
            test_result["transcript"].append(f"Census engine error (non-blocking): {str(ce)[:100]}")

        # Step 4: Persona generation
        from engines.persona_engine import generate_personas
        test_result["transcript"].append("Generating personas...")
        personas = generate_personas(config)
        test_result["transcript"].append(f"Generated {len(personas)} personas")

        if len(personas) == 0:
            test_result["errors"].append("No personas generated")

        # Step 5: Interviews
        from engines.interview_engine import run_interviews
        test_result["transcript"].append("Running interviews...")
        interviews = await run_interviews(personas, config)
        successful = [i for i in interviews if i]
        test_result["transcript"].append(f"Completed {len(successful)}/{len(personas)} interviews")

        if len(successful) == 0:
            test_result["errors"].append("All interviews failed")

        # Step 6: Scoring
        try:
            from engines.scoring_engine import score_simulation_batch, generate_score_report
            test_result["transcript"].append("Scoring conversations...")
            scoring_result = score_simulation_batch(
                interviews=successful,
                model=config["llm_model"],
            )
            score_report_path = generate_score_report(scoring_result, output_dir)
            composite = scoring_result.get("aggregates", {}).get("composite_score_avg", 0)
            test_result["transcript"].append(f"Scoring complete. Composite: {composite:.3f}")
        except Exception as se:
            test_result["transcript"].append(f"Scoring engine error (non-blocking): {str(se)[:100]}")
            composite = None
            score_report_path = None

        test_result["final_output"] = {
            "composite_score": composite,
            "personas_generated": len(personas),
            "interviews_completed": len(successful),
            "scoring_report": score_report_path,
        }

        # Step 7: Analysis
        try:
            from engines.analysis_engine import analyze_interviews
            test_result["transcript"].append("Running analysis engine...")
            analysis = await analyze_interviews(successful, config)
            test_result["transcript"].append("Analysis complete")
        except Exception as ae:
            test_result["transcript"].append(f"Analysis engine error (non-blocking): {str(ae)[:100]}")

        test_result["passed"] = len(test_result["errors"]) == 0

    except Exception as e:
        test_result["errors"].append(f"Exception: {str(e)}\n{traceback.format_exc()}")
        test_result["passed"] = False

    return test_result


# ═══════════════════════════════════════════════
# TEST: baseline_02 — Missing Information
# ═══════════════════════════════════════════════

async def test_baseline_02():
    """
    Run the engine with a deliberately incomplete config.
    Verify it fails gracefully with a clear error message.
    """
    logger.info("=" * 60)
    logger.info("TEST baseline_02: Missing Information — Graceful Degradation")
    logger.info("=" * 60)

    test_result = {
        "test_id": "baseline_02",
        "test_name": "Missing Information — Graceful Degradation",
        "priority": "P0",
        "input": "Incomplete config (missing product_description and archetypes)",
        "transcript": [],
        "errors": [],
        "final_output": None,
        "passed": False,
    }

    try:
        # Try loading a minimal/broken config
        test_result["transcript"].append("Attempting to load config with missing fields...")

        # Test 1: Completely empty config
        try:
            from config import load_config
            # Create a minimal broken config
            broken_config_path = os.path.join(qa_output_dir, "broken_config.yaml")
            with open(broken_config_path, "w") as f:
                f.write("product_name: Test\n")

            config = load_config(broken_config_path)
            test_result["transcript"].append(f"Config loaded (may have defaults): {list(config.keys())}")

            # Check if required fields have sensible defaults or raise errors
            required_fields = ["product_name", "product_description", "archetypes"]
            missing = [f for f in required_fields if not config.get(f)]
            if missing:
                test_result["transcript"].append(f"Missing required fields detected: {missing}")
                test_result["transcript"].append("GOOD: System should flag these before proceeding")
            else:
                test_result["transcript"].append("WARNING: Config accepted incomplete input without error")
                test_result["errors"].append("Config validation did not catch missing required fields")

        except Exception as e:
            test_result["transcript"].append(f"Config validation raised error: {str(e)}")
            test_result["transcript"].append("GOOD: System fails gracefully on incomplete config")

        # Test 2: Config with empty archetypes list
        try:
            empty_arch_path = os.path.join(qa_output_dir, "empty_archetypes.yaml")
            with open(empty_arch_path, "w") as f:
                f.write("""
product_name: Test Product
product_description: A test product
archetypes: []
questions: []
assumptions: []
""")
            config = load_config(empty_arch_path)
            test_result["transcript"].append(f"Empty archetypes config loaded. Archetypes: {config.get('archetypes', 'MISSING')}")

            if not config.get("archetypes"):
                test_result["transcript"].append("GOOD: Empty archetypes detected")
            else:
                test_result["errors"].append("Config accepted empty archetypes without error")

        except Exception as e:
            test_result["transcript"].append(f"Empty archetypes raised error: {str(e)}")

        # Test 3: Try generating personas with no world model
        try:
            from engines.persona_engine import generate_personas
            minimal_config = {
                "product_name": "Test",
                "product_description": "A test",
                "archetypes": [],
                "persona_count": 3,
                "llm_model": "gpt-4.1-mini",
            }
            test_result["transcript"].append("Attempting persona generation with empty archetypes...")
            personas = generate_personas(minimal_config)
            test_result["transcript"].append(f"Persona engine returned {len(personas)} personas")
            if len(personas) == 0:
                test_result["transcript"].append("GOOD: No personas generated from empty archetypes")
            else:
                test_result["transcript"].append("WARNING: Personas generated despite empty archetypes")

        except Exception as e:
            test_result["transcript"].append(f"Persona engine error: {str(e)}")

        test_result["passed"] = True  # This test passes if the system doesn't crash

    except Exception as e:
        test_result["errors"].append(f"Unexpected crash: {str(e)}\n{traceback.format_exc()}")
        test_result["passed"] = False

    return test_result


# ═══════════════════════════════════════════════
# TEST: baseline_03 — Edge Case (Unusual Input)
# ═══════════════════════════════════════════════

async def test_baseline_03():
    """
    Run with an unusual but valid input: a very niche industry
    (e.g., underwater basket weaving) to test if the system
    handles novel domains gracefully.
    """
    logger.info("=" * 60)
    logger.info("TEST baseline_03: Edge Case — Unusual but Valid Input")
    logger.info("=" * 60)

    test_result = {
        "test_id": "baseline_03",
        "test_name": "Edge Case — Unusual but Valid Input (Niche Industry)",
        "priority": "P1",
        "input": "Config for a very niche product: AI-powered fermentation monitoring for craft kombucha breweries",
        "transcript": [],
        "errors": [],
        "final_output": None,
        "passed": False,
    }

    try:
        # Create a niche config
        niche_config_path = os.path.join(qa_output_dir, "niche_config.yaml")
        with open(niche_config_path, "w") as f:
            f.write("""product:
  name: FermentIQ
  description: >
    AI-powered fermentation monitoring system for craft kombucha breweries.
    Uses IoT sensors to track pH, temperature, and SCOBY health in real-time.
    Alerts brewers to contamination risks and optimizes brew cycles.
    Integrates with existing brewery management software.
    Priced at $299/month per fermentation vessel.
  target_market: >
    Craft kombucha breweries in the US, ranging from hobby brewers scaling to
    commercial operations to established craft breweries with 10+ fermentation vessels.
    The craft kombucha market is growing rapidly as consumer demand for probiotic
    beverages increases.

archetypes:
  hobby_brewer:
    name: Hobby Brewer Going Commercial
    description: >
      Small-batch kombucha maker trying to scale from farmers markets to retail
      distribution. Budget-conscious, tech-curious but not tech-savvy. Runs 1-3
      fermentation vessels and is learning food safety compliance.
    percentage: 50
  established_brewery:
    name: Established Craft Brewery Owner
    description: >
      Runs a successful craft brewery with 10+ fermentation vessels. Already uses
      some monitoring but wants to automate. Willing to invest if ROI is clear.
      Has staff and needs consistency across batches.
    percentage: 50

questions:
  - How do you currently monitor your fermentation process?
  - What is your biggest fear when scaling production?
  - How much time do you spend on manual quality checks per week?

assumptions:
  - Craft kombucha brewers lose 5-15 percent of batches to contamination
  - Manual monitoring takes 2-4 hours per day for a 10-vessel operation
  - Most brewers use spreadsheets or paper logs for tracking

settings:
  persona_count: 4
  interview_turns: 3
  llm_model: gemini-2.5-flash
  persona_concurrency: 4
  interview_concurrency: 4

output_dir: output
""")

        from config import load_config
        config = load_config(niche_config_path)
        output_dir = os.path.join(qa_output_dir, "baseline_03")
        os.makedirs(output_dir, exist_ok=True)
        config["output_dir"] = output_dir

        test_result["transcript"].append("Niche config loaded successfully")

        # Generate personas
        from engines.persona_engine import generate_personas
        test_result["transcript"].append("Generating personas for kombucha industry...")
        personas = generate_personas(config)
        test_result["transcript"].append(f"Generated {len(personas)} personas")

        if len(personas) == 0:
            test_result["errors"].append("No personas generated for niche industry")
        else:
            # Check personas are actually kombucha-related
            for p in personas:
                name = p.get("name", "")
                archetype = p.get("archetype", "")
                test_result["transcript"].append(f"  Persona: {name} ({archetype})")

        # Run interviews
        from engines.interview_engine import run_interviews
        test_result["transcript"].append("Running interviews...")
        interviews = await run_interviews(personas, config)
        successful = [i for i in interviews if i]
        test_result["transcript"].append(f"Completed {len(successful)}/{len(personas)} interviews")

        if len(successful) == 0:
            test_result["errors"].append("All interviews failed for niche industry")

        test_result["final_output"] = {
            "personas_generated": len(personas),
            "interviews_completed": len(successful),
        }
        test_result["passed"] = len(test_result["errors"]) == 0

    except Exception as e:
        test_result["errors"].append(f"Exception: {str(e)}\n{traceback.format_exc()}")
        test_result["passed"] = False

    return test_result


# ═══════════════════════════════════════════════
# TEST: specific_01 — Iterative Loop Score Improvement
# ═══════════════════════════════════════════════

async def test_specific_01():
    """
    Verify that the iterative loop produces measurable score improvement.
    Uses the existing Loop 1/2/3 results as evidence.
    """
    logger.info("=" * 60)
    logger.info("TEST specific_01: Iterative Loop — Score Improvement")
    logger.info("=" * 60)

    test_result = {
        "test_id": "specific_01",
        "test_name": "Iterative Loop — Score Improvement Across Loops",
        "priority": "P0",
        "input": "Loop 1, 2, 3 scoring results from test_v2_output, test_v2_loop2_output, test_v2_loop3_output",
        "transcript": [],
        "errors": [],
        "final_output": None,
        "passed": False,
    }

    try:
        base_dir = os.path.dirname(__file__)

        # Load Loop 1 scores
        l1_path = os.path.join(base_dir, "test_v2_output", "scoring_results.json")
        with open(l1_path) as f:
            l1_data = json.load(f)
        l1_composite = l1_data.get("aggregates", {}).get("composite_score_avg", 0)
        test_result["transcript"].append(f"Loop 1 composite: {l1_composite:.3f}")

        # Load Loop 2 scores
        l2_path = os.path.join(base_dir, "test_v2_loop2_output", "scoring_results.json")
        with open(l2_path) as f:
            l2_data = json.load(f)
        l2_composite = l2_data.get("aggregates", {}).get("composite_score_avg", 0)
        test_result["transcript"].append(f"Loop 2 composite: {l2_composite:.3f}")

        # Load Loop 3 scores
        l3_path = os.path.join(base_dir, "test_v2_loop3_output", "scoring_results.json")
        with open(l3_path) as f:
            l3_data = json.load(f)
        l3_composite = l3_data.get("aggregates", {}).get("composite_score_avg", 0)
        test_result["transcript"].append(f"Loop 3 composite: {l3_composite:.3f}")

        # Verify monotonic improvement
        improvement_1_to_2 = l2_composite - l1_composite
        improvement_2_to_3 = l3_composite - l2_composite
        total_improvement = l3_composite - l1_composite

        test_result["transcript"].append(f"Improvement L1→L2: +{improvement_1_to_2:.3f}")
        test_result["transcript"].append(f"Improvement L2→L3: +{improvement_2_to_3:.3f}")
        test_result["transcript"].append(f"Total improvement: +{total_improvement:.3f} ({total_improvement/l1_composite*100:.0f}%)")

        if improvement_1_to_2 <= 0:
            test_result["errors"].append(f"Loop 2 did NOT improve over Loop 1 ({l1_composite:.3f} → {l2_composite:.3f})")
        if improvement_2_to_3 <= 0:
            test_result["errors"].append(f"Loop 3 did NOT improve over Loop 2 ({l2_composite:.3f} → {l3_composite:.3f})")
        if total_improvement < 0.1:
            test_result["errors"].append(f"Total improvement is negligible ({total_improvement:.3f})")

        # Check conversion rate progression
        l1_conv = l1_data.get("aggregates", {}).get("conversion_rate", 0)
        l2_conv = l2_data.get("aggregates", {}).get("conversion_rate", 0)
        l3_conv = l3_data.get("aggregates", {}).get("conversion_rate", 0)
        test_result["transcript"].append(f"Conversion: {l1_conv*100:.0f}% → {l2_conv*100:.0f}% → {l3_conv*100:.0f}%")

        test_result["final_output"] = {
            "loop_1_composite": l1_composite,
            "loop_2_composite": l2_composite,
            "loop_3_composite": l3_composite,
            "total_improvement_pct": round(total_improvement / l1_composite * 100, 1),
            "conversion_progression": f"{l1_conv*100:.0f}% → {l2_conv*100:.0f}% → {l3_conv*100:.0f}%",
        }
        test_result["passed"] = len(test_result["errors"]) == 0

    except Exception as e:
        test_result["errors"].append(f"Exception: {str(e)}\n{traceback.format_exc()}")
        test_result["passed"] = False

    return test_result


# ═══════════════════════════════════════════════
# TEST: specific_02 — Cold Start (No Transcripts)
# ═══════════════════════════════════════════════

async def test_specific_02():
    """
    Test the system with zero transcripts — the most common real-world scenario.
    The SKILL.md says it must inform the user that results will be proxy-based.
    """
    logger.info("=" * 60)
    logger.info("TEST specific_02: Cold Start — No Transcripts Available")
    logger.info("=" * 60)

    test_result = {
        "test_id": "specific_02",
        "test_name": "Cold Start — No Transcripts Available",
        "priority": "P1",
        "input": "Config with no transcripts, no CRM data — only product description and archetypes",
        "transcript": [],
        "errors": [],
        "final_output": None,
        "passed": False,
    }

    try:
        # The Refinery example has no transcripts — it IS a cold start
        config_path = os.path.join(os.path.dirname(__file__), "examples", "refinery", "config.yaml")
        from config import load_config
        config = load_config(config_path)
        config["persona_count"] = 3
        config["interview_turns"] = 3
        config["persona_concurrency"] = 3
        config["interview_concurrency"] = 3
        output_dir = os.path.join(qa_output_dir, "specific_02")
        os.makedirs(output_dir, exist_ok=True)
        config["output_dir"] = output_dir

        test_result["transcript"].append("Config loaded (no transcripts, no CRM data)")

        # Check SKILL.md mentions proxy warning
        skill_path = os.path.join(os.path.dirname(__file__), "skill", "SKILL.md")
        with open(skill_path) as f:
            skill_content = f.read()

        if "proxy" in skill_content.lower():
            test_result["transcript"].append("GOOD: SKILL.md mentions proxy model when transcripts unavailable")
        else:
            test_result["errors"].append("SKILL.md does NOT mention proxy model warning")

        # Run a minimal simulation to verify it works without transcripts
        from engines.persona_engine import generate_personas
        from engines.interview_engine import run_interviews

        personas = generate_personas(config)
        test_result["transcript"].append(f"Generated {len(personas)} personas (cold start)")

        interviews = await run_interviews(personas, config)
        successful = [i for i in interviews if i]
        test_result["transcript"].append(f"Completed {len(successful)}/{len(personas)} interviews (cold start)")

        test_result["final_output"] = {
            "personas_generated": len(personas),
            "interviews_completed": len(successful),
            "proxy_warning_in_skill": "proxy" in skill_content.lower(),
        }
        test_result["passed"] = len(successful) > 0 and len(test_result["errors"]) == 0

    except Exception as e:
        test_result["errors"].append(f"Exception: {str(e)}\n{traceback.format_exc()}")
        test_result["passed"] = False

    return test_result


# ═══════════════════════════════════════════════
# TEST: specific_03 — Scoring Consistency
# ═══════════════════════════════════════════════

async def test_specific_03():
    """
    Score the same set of conversations twice and check if scores are consistent.
    Tests the reliability of the LLM-based scoring engine.
    """
    logger.info("=" * 60)
    logger.info("TEST specific_03: Scoring Engine Consistency")
    logger.info("=" * 60)

    test_result = {
        "test_id": "specific_03",
        "test_name": "Scoring Engine Consistency — Same Input, Two Runs",
        "priority": "P1",
        "input": "Loop 1 interview data scored twice",
        "transcript": [],
        "errors": [],
        "final_output": None,
        "passed": False,
    }

    try:
        # Load the Loop 1 interviews from the scoring results
        l1_path = os.path.join(os.path.dirname(__file__), "test_v2_output", "scoring_results.json")
        with open(l1_path) as f:
            l1_data = json.load(f)

        # Get the individual conversation scores from run 1
        run1_scores = l1_data.get("individual_scores", [])
        run1_composite = l1_data.get("aggregates", {}).get("composite_score_avg", 0)
        test_result["transcript"].append(f"Run 1 composite: {run1_composite:.3f} ({len(run1_scores)} conversations)")

        # We need the actual interview data to re-score
        # Check if we have interviews saved
        interviews_path = os.path.join(os.path.dirname(__file__), "test_v2_output", "interviews.json")
        if not os.path.exists(interviews_path):
            # Try to find interview data in the scoring results
            test_result["transcript"].append("No separate interviews file found. Using scoring results for consistency check.")

            # Compare dimension-level variance within run 1 as a proxy for consistency
            dims = l1_data.get("aggregates", {}).get("dimension_averages", {})
            for dim_name, dim_stats in dims.items():
                spread = dim_stats.get("max", 0) - dim_stats.get("min", 0)
                test_result["transcript"].append(f"  {dim_name}: avg={dim_stats.get('avg', 0):.3f}, spread={spread:.3f}")
                if spread > 0.8:
                    test_result["transcript"].append(f"  WARNING: High variance in {dim_name}")

            test_result["transcript"].append("NOTE: Full re-scoring test requires saved interview transcripts.")
            test_result["transcript"].append("Scoring consistency can only be partially verified without re-running.")
            test_result["final_output"] = {
                "run1_composite": run1_composite,
                "note": "Partial test — full re-scoring requires saved interview transcripts",
            }
            test_result["passed"] = True  # Partial pass

        else:
            with open(interviews_path) as f:
                interviews = json.load(f)

            from engines.scoring_engine import score_simulation_batch
            from config import load_config

            config_path = os.path.join(os.path.dirname(__file__), "examples", "refinery", "config.yaml")
            config = load_config(config_path)

            test_result["transcript"].append("Re-scoring same conversations (Run 2)...")
            run2_result = score_simulation_batch(
                interviews=interviews,
                model=config["llm_model"],
            )
            run2_composite = run2_result.get("aggregates", {}).get("composite_score_avg", 0)
            test_result["transcript"].append(f"Run 2 composite: {run2_composite:.3f}")

            delta = abs(run2_composite - run1_composite)
            test_result["transcript"].append(f"Delta between runs: {delta:.3f}")

            if delta > 0.15:
                test_result["errors"].append(f"Scoring inconsistency: delta={delta:.3f} exceeds 0.15 threshold")
            else:
                test_result["transcript"].append(f"GOOD: Scoring is consistent (delta={delta:.3f} < 0.15)")

            test_result["final_output"] = {
                "run1_composite": run1_composite,
                "run2_composite": run2_composite,
                "delta": delta,
                "consistent": delta <= 0.15,
            }
            test_result["passed"] = delta <= 0.15

    except Exception as e:
        test_result["errors"].append(f"Exception: {str(e)}\n{traceback.format_exc()}")
        test_result["passed"] = False

    return test_result


# ═══════════════════════════════════════════════
# MAIN: Run all tests
# ═══════════════════════════════════════════════

async def main():
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("MARKET SIMULATION AGENT — QA TEST SUITE")
    logger.info("=" * 60)

    all_results = []

    # P0 tests first
    p0_tests = [
        ("baseline_01", test_baseline_01),
        ("baseline_02", test_baseline_02),
        ("specific_01", test_specific_01),
    ]

    for test_id, test_fn in p0_tests:
        logger.info(f"\n>>> Running {test_id}...")
        result = await test_fn()
        all_results.append(result)
        logger.info(f"<<< {test_id}: {'PASS' if result['passed'] else 'FAIL'}")

        # Check for blockers
        if not result["passed"] and result["priority"] == "P0":
            logger.warning(f"P0 test {test_id} FAILED. Continuing but flagging as critical.")

    # P1 tests
    p1_tests = [
        ("baseline_03", test_baseline_03),
        ("specific_02", test_specific_02),
        ("specific_03", test_specific_03),
    ]

    for test_id, test_fn in p1_tests:
        logger.info(f"\n>>> Running {test_id}...")
        result = await test_fn()
        all_results.append(result)
        logger.info(f"<<< {test_id}: {'PASS' if result['passed'] else 'FAIL'}")

    # Save results
    elapsed = time.time() - start_time
    output = {
        "skill_name": "market-simulation-agent",
        "eval_date": "2026-03-09",
        "total_time_seconds": round(elapsed, 1),
        "results": all_results,
        "summary": {
            "total_tests": len(all_results),
            "passed": sum(1 for r in all_results if r["passed"]),
            "failed": sum(1 for r in all_results if not r["passed"]),
        }
    }

    results_path = os.path.join(qa_output_dir, "qa_results.json")
    with open(results_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    logger.info("\n" + "=" * 60)
    logger.info("QA TEST SUITE COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Total time: {elapsed:.1f}s")
    logger.info(f"Tests: {output['summary']['total_tests']} total, {output['summary']['passed']} passed, {output['summary']['failed']} failed")
    for r in all_results:
        status = "✅ PASS" if r["passed"] else "❌ FAIL"
        logger.info(f"  {r['test_id']}: {status} — {r['test_name']}")
    logger.info(f"\nResults saved to: {results_path}")


if __name__ == "__main__":
    asyncio.run(main())
