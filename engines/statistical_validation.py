"""
Statistical Validation Engine — Confidence Intervals, Sample Size, and Significance.

Provides the statistical rigor layer that the simulation currently lacks:
  1. Sample size recommendations based on segment count and desired precision
  2. Confidence intervals for all proportion-based metrics
  3. Segment comparison significance testing
  4. Variance and standard deviation for score-based metrics
  5. Clear labeling of pre-registered vs. exploratory findings

All methods use simple, well-understood frequentist statistics that don't
require scipy or numpy — just math. This keeps the dependency footprint minimal.
"""
import math
from typing import Dict, Any, List, Optional, Tuple

from engines.logging_config import get_logger

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Sample Size Calculations
# ──────────────────────────────────────────────

def recommend_sample_size(
    num_segments: int,
    desired_confidence: float = 0.95,
    desired_margin: float = 0.10,
    min_per_segment: int = 20,
) -> Dict[str, Any]:
    """
    Recommend a minimum sample size for the simulation.

    Uses the standard formula for proportion estimation:
        n = (z^2 * p * (1-p)) / e^2

    where z = z-score for confidence level, p = 0.5 (worst case), e = margin of error.

    Then multiplies by the number of segments to ensure each segment has
    enough observations for meaningful sub-group analysis.

    Args:
        num_segments: Number of distinct archetypes/segments.
        desired_confidence: Confidence level (0.90, 0.95, 0.99).
        desired_margin: Acceptable margin of error (e.g., 0.10 = +/- 10%).
        min_per_segment: Minimum observations per segment.

    Returns:
        Dict with recommended total, per-segment minimums, and explanation.
    """
    z_scores = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}
    z = z_scores.get(desired_confidence, 1.96)

    # Minimum per-segment for proportion estimation
    p = 0.5  # Worst case (maximum variance)
    n_per_segment = math.ceil((z ** 2 * p * (1 - p)) / (desired_margin ** 2))
    n_per_segment = max(n_per_segment, min_per_segment)

    total_recommended = n_per_segment * num_segments

    # Also compute a "directional" tier (lower bar for exploratory research)
    n_directional = max(15, min_per_segment) * num_segments

    return {
        "recommended_total": total_recommended,
        "recommended_per_segment": n_per_segment,
        "directional_total": n_directional,
        "directional_per_segment": max(15, min_per_segment),
        "confidence_level": desired_confidence,
        "margin_of_error": desired_margin,
        "num_segments": num_segments,
        "explanation": (
            f"For {desired_confidence:.0%} confidence with +/-{desired_margin:.0%} margin of error "
            f"across {num_segments} segments, you need at least {n_per_segment} personas per segment "
            f"({total_recommended} total). For directional insights only, {n_directional} total "
            f"({max(15, min_per_segment)} per segment) is a reasonable minimum."
        ),
    }


def check_sample_adequacy(
    persona_count: int,
    archetype_counts: Dict[str, int],
    min_per_segment: int = 20,
) -> Dict[str, Any]:
    """
    Check whether the current sample is adequate for the number of segments.

    Args:
        persona_count: Total personas in the simulation.
        archetype_counts: Dict mapping archetype name to count.
        min_per_segment: Minimum per segment for reliable analysis.

    Returns:
        Dict with adequacy assessment and specific warnings.
    """
    warnings = []
    underpowered_segments = []

    for archetype, count in archetype_counts.items():
        if count < min_per_segment:
            underpowered_segments.append(archetype)
            warnings.append(
                f"Segment '{archetype}' has only {count} personas (minimum {min_per_segment} "
                f"recommended). Sub-group findings for this segment may not be reliable."
            )

    # Overall assessment
    if not underpowered_segments:
        adequacy = "adequate"
        summary = (
            f"Sample size of {persona_count} with {len(archetype_counts)} segments is adequate. "
            f"All segments have {min_per_segment}+ personas."
        )
    elif len(underpowered_segments) <= len(archetype_counts) // 2:
        adequacy = "partially_adequate"
        summary = (
            f"Sample size of {persona_count} is adequate for overall analysis but "
            f"{len(underpowered_segments)} of {len(archetype_counts)} segments are underpowered. "
            f"Sub-group comparisons involving these segments should be interpreted cautiously."
        )
    else:
        adequacy = "underpowered"
        summary = (
            f"Sample size of {persona_count} is too small for {len(archetype_counts)} segments. "
            f"{len(underpowered_segments)} segments have fewer than {min_per_segment} personas. "
            f"Consider increasing persona_count or reducing the number of archetypes."
        )

    return {
        "adequacy": adequacy,
        "summary": summary,
        "underpowered_segments": underpowered_segments,
        "warnings": warnings,
        "persona_count": persona_count,
        "segment_counts": archetype_counts,
    }


# ──────────────────────────────────────────────
# Confidence Intervals
# ──────────────────────────────────────────────

def wilson_score_interval(
    successes: int,
    total: int,
    confidence: float = 0.95,
) -> Tuple[float, float]:
    """
    Wilson score interval for a proportion — more accurate than the normal
    approximation for small samples and extreme proportions.

    Args:
        successes: Number of "positive" outcomes.
        total: Total observations.
        confidence: Confidence level.

    Returns:
        Tuple of (lower_bound, upper_bound) as proportions.
    """
    if total == 0:
        return (0.0, 1.0)

    z_scores = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}
    z = z_scores.get(confidence, 1.96)

    p_hat = successes / total
    denominator = 1 + z ** 2 / total
    center = (p_hat + z ** 2 / (2 * total)) / denominator
    spread = z * math.sqrt((p_hat * (1 - p_hat) + z ** 2 / (4 * total)) / total) / denominator

    lower = max(0.0, center - spread)
    upper = min(1.0, center + spread)

    return (round(lower, 4), round(upper, 4))


def proportion_with_ci(
    successes: int,
    total: int,
    confidence: float = 0.95,
    label: str = "",
) -> Dict[str, Any]:
    """
    Compute a proportion with its Wilson score confidence interval.

    Returns a dict suitable for embedding in reports.
    """
    if total == 0:
        return {
            "proportion": 0.0,
            "ci_lower": 0.0,
            "ci_upper": 1.0,
            "n": 0,
            "label": label,
            "display": f"{label}: 0.0% (n=0, insufficient data)",
        }

    prop = successes / total
    lower, upper = wilson_score_interval(successes, total, confidence)

    return {
        "proportion": round(prop, 4),
        "ci_lower": lower,
        "ci_upper": upper,
        "n": total,
        "confidence": confidence,
        "label": label,
        "display": (
            f"{label}: {prop:.1%} ({successes}/{total}), "
            f"{confidence:.0%} CI [{lower:.1%}, {upper:.1%}]"
        ),
    }


# ──────────────────────────────────────────────
# Score Statistics (mean, std dev, variance)
# ──────────────────────────────────────────────

def score_statistics(
    values: List[float],
    label: str = "",
) -> Dict[str, Any]:
    """
    Compute descriptive statistics for a list of scores.

    Args:
        values: List of numeric values.
        label: Human-readable label for this metric.

    Returns:
        Dict with mean, std_dev, variance, min, max, n, and CI for the mean.
    """
    if not values:
        return {
            "mean": 0.0,
            "std_dev": 0.0,
            "variance": 0.0,
            "min": 0.0,
            "max": 0.0,
            "n": 0,
            "ci_lower": 0.0,
            "ci_upper": 0.0,
            "label": label,
        }

    n = len(values)
    mean = sum(values) / n

    if n < 2:
        std_dev = 0.0
    else:
        variance = sum((x - mean) ** 2 for x in values) / (n - 1)  # Bessel's correction
        std_dev = math.sqrt(variance)

    variance = std_dev ** 2

    # 95% CI for the mean (t-distribution approximated as z for n >= 20)
    z = 1.96
    if n >= 2:
        se = std_dev / math.sqrt(n)
        ci_lower = mean - z * se
        ci_upper = mean + z * se
    else:
        ci_lower = mean
        ci_upper = mean

    return {
        "mean": round(mean, 4),
        "std_dev": round(std_dev, 4),
        "variance": round(variance, 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "n": n,
        "ci_lower": round(ci_lower, 4),
        "ci_upper": round(ci_upper, 4),
        "label": label,
    }


# ──────────────────────────────────────────────
# Segment Comparison (two-proportion z-test)
# ──────────────────────────────────────────────

def two_proportion_z_test(
    successes_a: int,
    total_a: int,
    successes_b: int,
    total_b: int,
) -> Dict[str, Any]:
    """
    Two-proportion z-test for comparing rates between two segments.

    Tests H0: p_a = p_b vs H1: p_a != p_b.

    Args:
        successes_a, total_a: Counts for segment A.
        successes_b, total_b: Counts for segment B.

    Returns:
        Dict with z-statistic, p-value approximation, and significance flag.
    """
    if total_a == 0 or total_b == 0:
        return {
            "z_statistic": 0.0,
            "p_value_approx": 1.0,
            "significant_at_05": False,
            "significant_at_10": False,
            "insufficient_data": True,
        }

    p_a = successes_a / total_a
    p_b = successes_b / total_b

    # Pooled proportion
    p_pool = (successes_a + successes_b) / (total_a + total_b)

    # Standard error of the difference
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / total_a + 1 / total_b))

    if se == 0:
        return {
            "z_statistic": 0.0,
            "p_value_approx": 1.0,
            "significant_at_05": False,
            "significant_at_10": False,
            "insufficient_data": False,
        }

    z = (p_a - p_b) / se

    # Approximate p-value using standard normal CDF approximation
    # (Abramowitz & Stegun approximation)
    p_value = _approx_two_tail_p(abs(z))

    return {
        "z_statistic": round(z, 4),
        "p_value_approx": round(p_value, 4),
        "significant_at_05": p_value < 0.05,
        "significant_at_10": p_value < 0.10,
        "segment_a_rate": round(p_a, 4),
        "segment_b_rate": round(p_b, 4),
        "difference": round(p_a - p_b, 4),
        "insufficient_data": False,
    }


def _approx_two_tail_p(z: float) -> float:
    """
    Approximate two-tailed p-value for a z-statistic.
    Uses the Abramowitz & Stegun approximation (formula 26.2.17).
    """
    if z < 0:
        z = -z

    # Constants
    b0 = 0.2316419
    b1 = 0.319381530
    b2 = -0.356563782
    b3 = 1.781477937
    b4 = -1.821255978
    b5 = 1.330274429

    t = 1.0 / (1.0 + b0 * z)
    phi = math.exp(-z * z / 2.0) / math.sqrt(2.0 * math.pi)

    one_tail = phi * (b1 * t + b2 * t**2 + b3 * t**3 + b4 * t**4 + b5 * t**5)
    two_tail = 2.0 * one_tail

    return min(1.0, max(0.0, two_tail))


# ──────────────────────────────────────────────
# Finding Classification
# ──────────────────────────────────────────────

def classify_findings(
    assumptions: List[str],
    questions: List[str],
    emergent_themes: List[str],
) -> Dict[str, List[Dict[str, str]]]:
    """
    Classify findings into pre-registered hypotheses vs. exploratory findings.

    Pre-registered: The assumptions and questions the user specified upfront.
    Exploratory: Themes that emerged from the data that weren't pre-specified.

    This distinction is critical for statistical interpretation:
    - Pre-registered findings can be evaluated for validation/invalidation
    - Exploratory findings should be treated as hypotheses for future testing
    """
    pre_registered = []
    for a in assumptions:
        pre_registered.append({
            "item": a,
            "type": "assumption",
            "classification": "pre-registered",
            "interpretation_note": "This was specified before the simulation. Validation scores are interpretable.",
        })
    for q in questions:
        pre_registered.append({
            "item": q,
            "type": "question",
            "classification": "pre-registered",
            "interpretation_note": "This was specified before the simulation. Responses are interpretable.",
        })

    exploratory = []
    for theme in emergent_themes:
        exploratory.append({
            "item": theme,
            "type": "emergent_theme",
            "classification": "exploratory",
            "interpretation_note": (
                "This theme emerged from the data and was NOT pre-specified. "
                "Treat as a hypothesis for future validation, not as a confirmed finding."
            ),
        })

    return {
        "pre_registered": pre_registered,
        "exploratory": exploratory,
        "total_pre_registered": len(pre_registered),
        "total_exploratory": len(exploratory),
    }


# ──────────────────────────────────────────────
# Report Section Generator
# ──────────────────────────────────────────────

def generate_statistical_appendix(
    audience_stats: Dict[str, Any],
    config: Dict[str, Any],
    context_quality: Dict[str, Any],
) -> str:
    """
    Generate a statistical appendix for the simulation report.

    This section provides the statistical context that readers need
    to properly interpret the findings.
    """
    persona_count = audience_stats.get("total_interviews", 0)
    archetype_dist = audience_stats.get("archetype_distribution", {})
    num_segments = len(archetype_dist)

    # Sample adequacy
    adequacy = check_sample_adequacy(persona_count, archetype_dist)

    # Sample size recommendation
    recommendation = recommend_sample_size(num_segments)

    lines = [
        "## Statistical Appendix",
        "",
        "### Context Quality",
        "",
        context_quality.get("report_caveat", "Context quality not assessed."),
        "",
        "### Sample Adequacy",
        "",
        f"**Assessment: {adequacy['adequacy'].replace('_', ' ').title()}**",
        "",
        adequacy["summary"],
        "",
    ]

    if adequacy["warnings"]:
        lines.append("**Segment Warnings:**")
        for w in adequacy["warnings"]:
            lines.append(f"- {w}")
        lines.append("")

    lines.extend([
        "### Sample Size Guidance",
        "",
        recommendation["explanation"],
        "",
        f"| Tier | Per Segment | Total |",
        f"|------|-------------|-------|",
        f"| Statistically rigorous | {recommendation['recommended_per_segment']} | {recommendation['recommended_total']} |",
        f"| Directional insights | {recommendation['directional_per_segment']} | {recommendation['directional_total']} |",
        f"| This simulation | {min(archetype_dist.values()) if archetype_dist else 0} (smallest segment) | {persona_count} |",
        "",
        "### Interpretation Notes",
        "",
        "- **Pre-registered hypotheses** (user-specified assumptions and questions) can be "
        "evaluated for validation/invalidation with the data collected.",
        "- **Emergent themes** (patterns that emerged during analysis) should be treated as "
        "hypotheses for future testing, not confirmed findings.",
        "- All percentages should be interpreted with their confidence intervals. "
        "A reported rate of 60% with a wide CI (e.g., 35%-82%) is much less certain "
        "than one with a narrow CI (e.g., 55%-65%).",
        "- Sub-group comparisons involving fewer than 20 observations should be treated "
        "as directional only.",
        "",
        "### Simulation Limitations",
        "",
        "- Personas are LLM-generated and may not capture the full range of real human behavior.",
        "- The same model family generates and evaluates responses, introducing potential systematic bias.",
        "- Text-based simulation cannot capture non-verbal cues, environmental factors, or "
        "true emotional responses.",
        "- Results should be validated with real customer interviews before making major decisions.",
        "- Qualitative research typically reaches thematic saturation at 12-30 interviews; "
        "this simulation provides broader coverage but shallower depth per persona.",
    ])

    return "\n".join(lines)
