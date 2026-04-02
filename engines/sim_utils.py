"""
Simulation Utilities — Non-LLM helpers for Claude Code skill flow.

When running as a Claude Code skill, Claude IS the LLM. These utilities
handle the computational/analytical work that Claude Code calls via Python:
  - Config validation
  - Context quality grading
  - Persona metadata assignment (dispositions, skepticism scores)
  - Bias detection (post-hoc analysis on interview data)
  - Statistical validation (confidence intervals, sample adequacy)
  - Report assembly

None of these functions make LLM API calls. They are pure computation.

This module is a facade — it re-exports from the underlying engines to give
the skill a single import point. Functions that would duplicate engine logic
delegate directly rather than reimplementing.
"""
import json
import os
import sys
from datetime import datetime
from typing import Dict, Any, List, Optional

# Add project root to path if not already present
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def validate_config(config_path: str) -> Dict[str, Any]:
    """
    Validate a YAML config and return the resolved config dict.
    Raises ConfigValidationError with clear messages on failure.
    """
    from config import load_config
    return load_config(config_path)


def grade_context_quality(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Grade the quality of context provided (A-F).
    Returns: {grade, score, details, warnings, report_caveat}
    """
    from engines.context_quality import compute_context_quality
    return compute_context_quality(config)


def assign_persona_metadata(
    persona: Dict[str, Any],
    archetype_key: str,
    archetype: Dict[str, Any],
    disposition_weights: Dict[str, Any],
    interaction_context: str = "warm_demo",
) -> Dict[str, Any]:
    """
    Assign simulation metadata (disposition, skepticism score) to a persona.
    Delegates to persona_engine._enrich_persona().
    """
    from engines.persona_engine import _enrich_persona
    return _enrich_persona(
        persona, archetype_key, archetype, disposition_weights, interaction_context
    )


def check_sample_adequacy(
    persona_count: int,
    num_segments: int,
) -> Dict[str, Any]:
    """
    Check if sample size is adequate for the number of segments.
    Delegates to statistical_validation for the recommendation,
    returns a simplified result dict for the skill flow.
    """
    from engines.statistical_validation import recommend_sample_size
    rec = recommend_sample_size(num_segments)
    recommended_total = rec["recommended_total"]
    directional_total = rec["directional_total"]
    per_segment = persona_count // max(num_segments, 1)
    adequate = persona_count >= recommended_total

    result = {
        "adequate": adequate,
        "recommended_total": recommended_total,
        "directional_total": directional_total,
        "actual": persona_count,
        "per_segment": per_segment,
        "explanation": rec["explanation"],
    }

    if not adequate and persona_count >= directional_total:
        result["warning"] = (
            f"Sample size ({persona_count}) is below the statistically rigorous minimum "
            f"({recommended_total}) but sufficient for directional insights."
        )
    elif not adequate:
        result["warning"] = (
            f"Sample size ({persona_count}) is below recommended minimum "
            f"({directional_total} directional, {recommended_total} rigorous) "
            f"for {num_segments} segments."
        )
    if per_segment < 20:
        result["segment_warning"] = (
            f"Only {per_segment} personas per segment — sub-group findings "
            f"will be flagged as unreliable. Consider 20+ per segment."
        )

    return result


def run_bias_audit(interviews: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run post-hoc bias detection on completed interviews."""
    from engines.bias_detection import run_bias_audit as _run_audit
    return _run_audit(interviews)


def generate_statistical_appendix(
    interviews: List[Dict[str, Any]],
    personas: List[Dict[str, Any]],
) -> str:
    """Generate a statistical appendix section for the report (markdown)."""
    from engines.statistical_validation import generate_statistical_appendix as _gen
    return _gen(interviews, personas)


def get_format_info(experiment_format: str) -> Dict[str, Any]:
    """
    Get format-specific information for the skill flow.
    Uses validate_experiment_format() which returns prompt extensions,
    metrics, and caveats in one call.
    """
    from engines.experiment_formats import validate_experiment_format
    return validate_experiment_format(experiment_format, {})


def save_simulation_output(
    output_dir: str,
    personas: List[Dict[str, Any]],
    interviews: List[Dict[str, Any]],
    report_md: str,
    transcripts_md: str,
    config: Dict[str, Any],
    bias_audit: Optional[Dict] = None,
    context_quality: Optional[Dict] = None,
    scoring_results: Optional[Dict] = None,
) -> Dict[str, str]:
    """
    Save all simulation artifacts to the output directory.
    Returns: {file_name: file_path} for all saved files.
    """
    os.makedirs(output_dir, exist_ok=True)
    saved = {}

    def _save(name, content):
        path = os.path.join(output_dir, name)
        if isinstance(content, str):
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        else:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(content, f, indent=2, default=str)
        saved[name] = path

    _save("report.md", report_md)
    _save("transcripts.md", transcripts_md)
    _save("personas.json", personas)
    _save("interviews.json", interviews)

    if bias_audit:
        _save("bias_audit.json", bias_audit)
    if context_quality:
        _save("context_quality.json", context_quality)
    if scoring_results:
        _save("scoring_results.json", scoring_results)

    metadata = {
        "timestamp": datetime.now().isoformat(),
        "persona_count": len(personas),
        "interview_count": len(interviews),
        "context_quality_grade": context_quality.get("grade", "N/A") if context_quality else "N/A",
        "bias_risk": bias_audit.get("overall_risk", "N/A") if bias_audit else "N/A",
        "config_snapshot": {
            k: v for k, v in config.items()
            if k not in ("archetypes", "disposition_weights")
        },
    }
    _save("run_metadata.json", metadata)

    return saved


# ──────────────────────────────────────────────
# CLI entry point for quick utility calls
# ──────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 engines/sim_utils.py <command> [args]")
        print("Commands: validate, context-quality, sample-check")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "validate":
        config_path = sys.argv[2]
        try:
            cfg = validate_config(config_path)
            print(json.dumps({
                "status": "valid",
                "product": cfg["product_name"],
                "personas": cfg["persona_count"],
                "model": cfg["llm_model"],
                "format": cfg["experiment_format"],
            }, indent=2))
        except Exception as e:
            print(json.dumps({"status": "error", "message": str(e)}, indent=2))
            sys.exit(1)

    elif cmd == "context-quality":
        config_path = sys.argv[2]
        cfg = validate_config(config_path)
        quality = grade_context_quality(cfg)
        print(json.dumps(quality, indent=2))

    elif cmd == "sample-check":
        count = int(sys.argv[2])
        segments = int(sys.argv[3])
        result = check_sample_adequacy(count, segments)
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
