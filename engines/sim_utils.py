"""
Simulation Utilities — Non-LLM helpers for Claude Code skill flow.

When running as a Claude Code skill, Claude IS the LLM. These utilities
handle the computational/analytical work that Claude Code calls via Python:
  - Config validation
  - Context quality grading
  - Persona metadata assignment (dispositions, skepticism scores)
  - Bias detection (post-hoc analysis on interview data)
  - Statistical validation (confidence intervals, sample adequacy)
  - Scoring computation (deterministic 7-dimension scoring)
  - Report assembly

None of these functions make LLM API calls. They are pure computation.
"""
import json
import os
import random
import sys
from datetime import datetime
from typing import Dict, Any, List, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
    This is the non-LLM part of persona generation — Claude generates the
    persona content, this function adds the simulation mechanics.
    """
    from engines.persona_engine import _assign_disposition, _assign_skepticism_score

    persona["archetype"] = archetype_key
    persona["archetype_name"] = archetype.get("name", archetype_key)
    persona["disposition"] = _assign_disposition(
        archetype_key, disposition_weights, interaction_context
    )
    persona["skepticism_score"] = _assign_skepticism_score(archetype)
    return persona


def compute_sample_allocation(
    archetypes: Dict[str, Any],
    persona_count: int,
) -> Dict[str, int]:
    """
    Compute how many personas to generate per archetype based on weights.
    Returns: {archetype_key: count}
    """
    total_weight = sum(a.get("typical_weight", 0.1) for a in archetypes.values())
    allocation = {}
    remaining = persona_count

    keys = list(archetypes.keys())
    for i, key in enumerate(keys):
        weight = archetypes[key].get("typical_weight", 0.1)
        if i == len(keys) - 1:
            allocation[key] = remaining
        else:
            count = max(1, round(persona_count * weight / total_weight))
            allocation[key] = count
            remaining -= count

    return allocation


def check_sample_adequacy(
    persona_count: int,
    num_segments: int,
) -> Dict[str, Any]:
    """
    Check if sample size is adequate for the number of segments.
    Returns: {adequate, recommended, per_segment, warning}
    """
    from engines.statistical_validation import recommend_sample_size
    recommended = recommend_sample_size(num_segments)
    per_segment = persona_count // max(num_segments, 1)
    adequate = persona_count >= recommended

    result = {
        "adequate": adequate,
        "recommended": recommended,
        "actual": persona_count,
        "per_segment": per_segment,
    }

    if not adequate:
        result["warning"] = (
            f"Sample size ({persona_count}) is below recommended minimum "
            f"({recommended}) for {num_segments} segments. "
            f"Results should be treated as directional only."
        )
    if per_segment < 20:
        result["segment_warning"] = (
            f"Only {per_segment} personas per segment — sub-group findings "
            f"will be flagged as unreliable. Consider 20+ per segment."
        )

    return result


def run_bias_audit(interviews: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Run post-hoc bias detection on completed interviews.
    Returns the full bias audit dict.
    """
    from engines.bias_detection import run_bias_audit as _run_audit
    return _run_audit(interviews)


def generate_statistical_appendix(
    interviews: List[Dict[str, Any]],
    personas: List[Dict[str, Any]],
) -> str:
    """
    Generate a statistical appendix section for the report.
    Returns markdown text.
    """
    from engines.statistical_validation import generate_statistical_appendix as _gen
    return _gen(interviews, personas)


def score_conversations(
    interviews: List[Dict[str, Any]],
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Score conversations using the deterministic 7-dimension scoring engine.
    Note: Some dimensions in the scoring engine use LLM calls for turn analysis.
    For fully LLM-free scoring, use score_conversations_basic().
    """
    from engines.scoring_engine import score_simulation_batch
    return score_simulation_batch(interviews, weights=weights)


def get_format_prompts(experiment_format: str) -> Dict[str, str]:
    """
    Get format-specific interviewer prompt extensions and metrics.
    Returns: {interviewer_extension, metrics_note, limitation_caveat}
    """
    from engines.experiment_formats import (
        get_interviewer_prompt_extension,
        get_format_metrics,
        get_format_limitations,
    )
    return {
        "interviewer_extension": get_interviewer_prompt_extension(experiment_format),
        "metrics_note": get_format_metrics(experiment_format),
        "limitation_caveat": get_format_limitations(experiment_format),
    }


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

    # Run metadata
    metadata = {
        "timestamp": datetime.now().isoformat(),
        "persona_count": len(personas),
        "interview_count": len(interviews),
        "context_quality_grade": context_quality.get("grade", "N/A") if context_quality else "N/A",
        "bias_risk": bias_audit.get("overall_risk", "N/A") if bias_audit else "N/A",
        "config_snapshot": {
            k: v for k, v in config.items()
            if k not in ("archetypes", "disposition_weights")  # keep metadata compact
        },
    }
    _save("run_metadata.json", metadata)

    return saved


# ──────────────────────────────────────────────
# CLI entry point for quick utility calls
# ──────────────────────────────────────────────

if __name__ == "__main__":
    """
    Quick utility CLI. Usage:
      python3 engines/sim_utils.py validate path/to/config.yaml
      python3 engines/sim_utils.py context-quality path/to/config.yaml
      python3 engines/sim_utils.py sample-check 30 6
    """
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
