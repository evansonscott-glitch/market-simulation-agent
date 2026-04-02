"""
Experiment Format Engine — Format-Specific Validation and Metrics.

Different experiment formats (webpage viewing, PDF reading, form filling,
in-person interviews) require different measurement approaches, different
interviewer prompts, and different metrics. This module:

  1. Defines supported experiment formats with their specific requirements
  2. Generates format-specific interviewer prompts
  3. Defines format-specific metrics
  4. Adds format-specific caveats to the report

Supported formats:
  - interview:         Standard 1:1 simulated customer interview
  - focus_group:       Multi-persona moderated discussion
  - sales_sequence:    Multi-touch outreach over time
  - webpage_review:    Persona reacts to a described webpage/landing page
  - document_review:   Persona reacts to a described PDF/whitepaper/pitch deck
  - form_test:         Persona walks through a form/signup flow step-by-step
  - in_person_interview: Simulated in-person with explicit caveats about limitations
"""
from typing import Dict, Any, List, Optional

from engines.logging_config import get_logger

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Format Definitions
# ──────────────────────────────────────────────

EXPERIMENT_FORMATS = {
    "interview": {
        "name": "1:1 Customer Interview",
        "description": "Standard simulated customer discovery interview.",
        "requires_content": False,
        "content_field": None,
        "specific_metrics": [
            "validation_score",
            "evidence_quality",
            "objection_depth",
            "willingness_to_pay_signal",
        ],
        "caveats": [],
    },
    "focus_group": {
        "name": "Focus Group Discussion",
        "description": "Multi-persona moderated group discussion.",
        "requires_content": False,
        "content_field": None,
        "specific_metrics": [
            "opinion_shift_count",
            "social_proof_events",
            "dominant_voice_index",
            "consensus_level",
        ],
        "caveats": [
            "LLM-simulated group dynamics may understate conformity pressure.",
            "Real focus groups have physical proximity and non-verbal cues that affect behavior.",
        ],
    },
    "sales_sequence": {
        "name": "Multi-Touch Sales Sequence",
        "description": "Simulated outreach across multiple touchpoints over time.",
        "requires_content": False,
        "content_field": None,
        "specific_metrics": [
            "conversion_by_round",
            "drop_off_round",
            "channel_effectiveness",
            "attitude_drift",
        ],
        "caveats": [
            "Simulated time gaps don't capture real-world urgency decay or competing offers.",
            "SMS/email simulations can't capture read rates or open rates.",
        ],
    },
    "webpage_review": {
        "name": "Webpage / Landing Page Review",
        "description": (
            "Persona reviews a described webpage and provides reactions. "
            "Requires a structured description of the page content."
        ),
        "requires_content": True,
        "content_field": "webpage_description",
        "specific_metrics": [
            "first_impression_sentiment",
            "cta_comprehension",
            "value_prop_clarity",
            "trust_signal_recognition",
            "above_fold_engagement",
            "pricing_comprehension",
            "bounce_intent",
        ],
        "caveats": [
            "Personas react to a text description of the page, not the visual design itself.",
            "Layout, typography, color, imagery, and load speed cannot be simulated.",
            "Real webpage testing should use tools like Hotjar, FullStory, or user testing platforms.",
            "This simulation tests messaging and content strategy, not UX/UI design.",
        ],
    },
    "document_review": {
        "name": "Document / PDF Review",
        "description": (
            "Persona reviews a described document (whitepaper, pitch deck, case study) "
            "and provides reactions section by section."
        ),
        "requires_content": True,
        "content_field": "document_description",
        "specific_metrics": [
            "section_engagement",
            "key_takeaway_accuracy",
            "credibility_assessment",
            "action_intent",
            "share_intent",
            "read_through_intent",
        ],
        "caveats": [
            "Personas react to described content, not actual document formatting/design.",
            "Real document engagement metrics (scroll depth, time per page) cannot be simulated.",
            "Charts, graphs, and visual data cannot be presented to personas.",
            "This tests content strategy and argumentation, not document design.",
        ],
    },
    "form_test": {
        "name": "Form / Signup Flow Test",
        "description": (
            "Persona walks through a form or signup flow step-by-step. "
            "Requires a structured description of each form step/field."
        ),
        "requires_content": True,
        "content_field": "form_steps",
        "specific_metrics": [
            "completion_intent",
            "field_level_friction",
            "abandonment_trigger",
            "data_sharing_comfort",
            "expected_completion_time",
            "confusion_points",
        ],
        "caveats": [
            "Simulated form completion doesn't capture real UX friction (typing, validation errors).",
            "Auto-fill behavior, mobile vs desktop differences, and accessibility issues are not tested.",
            "Real form testing should use analytics tools and A/B testing platforms.",
            "This tests information requirements and perceived friction, not UX mechanics.",
        ],
    },
    "in_person_interview": {
        "name": "In-Person Interview Simulation",
        "description": (
            "Simulated in-person interview with explicit acknowledgment of "
            "what text-based simulation cannot capture."
        ),
        "requires_content": False,
        "content_field": None,
        "specific_metrics": [
            "validation_score",
            "evidence_quality",
            "rapport_proxy",
            "elaboration_depth",
        ],
        "caveats": [
            "IMPORTANT: This is a text-based simulation of an in-person interview. "
            "The following real-world factors are NOT captured:",
            "  - Body language, facial expressions, and non-verbal cues",
            "  - Interviewer appearance, demeanor, and rapport-building",
            "  - Physical environment (office, coffee shop, conference room)",
            "  - Interruptions, distractions, and time pressure",
            "  - Social desirability bias (stronger in person than via text)",
            "  - Power dynamics based on physical presence",
            "Real in-person interviews should complement this simulation for full validation.",
        ],
    },
}


# ──────────────────────────────────────────────
# Format-Specific Interviewer Prompt Extensions
# ──────────────────────────────────────────────

FORMAT_INTERVIEWER_PROMPTS = {
    "webpage_review": """
## FORMAT-SPECIFIC INSTRUCTIONS: Webpage Review

You are showing the persona a webpage/landing page. Walk them through it section by section.

1. Start by describing what they see above the fold (headline, subhead, hero image concept, CTA).
2. Ask: "What's your first impression? What stands out to you?"
3. Walk through the pricing section (if any): "Here's how the pricing works: [describe]. What's your reaction?"
4. Show them the social proof / testimonials section: "Other customers say [X]. Does that resonate?"
5. Show them the CTA: "The main call to action is [X]. Would you click it? Why or why not?"
6. Final question: "If you landed on this page from a Google search, would you stay or bounce? What would make you stay?"

Use the webpage description provided to ground your questions in specific content.""",

    "document_review": """
## FORMAT-SPECIFIC INSTRUCTIONS: Document Review

You are presenting a document (whitepaper/pitch deck/case study) to the persona.

1. Start with the title and executive summary: "This document is called [X]. The key claim is [Y]."
2. Walk through each major section, asking for reactions: "The next section covers [topic]. Here's the key argument: [summary]. What do you think?"
3. For data/claims: "The document states [specific claim]. Does that ring true based on your experience?"
4. For case studies: "Here's an example they share: [summary]. Is that relevant to your situation?"
5. At the end: "Would you share this with a colleague? Would you read the whole thing or skim?"
6. Final: "What's the single thing you'd remember from this document tomorrow?"

Use the document description to present real content from the document.""",

    "form_test": """
## FORMAT-SPECIFIC INSTRUCTIONS: Form / Signup Flow Test

You are walking the persona through a form or signup process step by step.

1. Present each step/field one at a time: "The first thing they ask for is [field]. Would you fill this in?"
2. For each field, ask about friction: "How do you feel about providing this information? Any hesitation?"
3. For multi-step forms: "Now you're on step 2 of 4. They're asking for [fields]. Still with us?"
4. For sensitive fields (email, phone, payment): "They're asking for your [sensitive info] at this point. Would you provide it?"
5. Track abandonment: "At this point, would you still be completing the form, or would you have left?"
6. Final: "If you completed the form, what would you expect to happen next? How soon?"

Present the actual form steps/fields from the provided description.""",

    "in_person_interview": """
## FORMAT-SPECIFIC INSTRUCTIONS: In-Person Interview Simulation

You are simulating an in-person customer discovery interview. Since this is text-based:

1. Be more conversational and warm than a standard interview. In-person interviews have more rapport.
2. Include small talk and warmth: "Thanks for meeting with me today. I appreciate you taking the time."
3. Ask about their environment/context: "Tell me about your day-to-day — what does a typical week look like?"
4. Use more follow-up probes: "That's interesting — tell me more about that."
5. Be more patient with tangents — in-person interviews naturally wander more.
6. At the end, ask: "Is there anything I didn't ask about that you think is important?"

Note: Simulate the CONTENT of an in-person interview, but acknowledge that non-verbal cues and physical rapport cannot be captured.""",
}


# ──────────────────────────────────────────────
# Validation and Config
# ──────────────────────────────────────────────

def validate_experiment_format(
    format_type: str,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Validate that the config has everything needed for the chosen experiment format.

    Args:
        format_type: One of the EXPERIMENT_FORMATS keys.
        config: The simulation config dict.

    Returns:
        Dict with validation result, warnings, and the format definition.
    """
    if format_type not in EXPERIMENT_FORMATS:
        return {
            "valid": False,
            "error": f"Unknown experiment format '{format_type}'. "
                     f"Valid formats: {', '.join(EXPERIMENT_FORMATS.keys())}",
            "format_def": None,
        }

    format_def = EXPERIMENT_FORMATS[format_type]
    warnings = []

    # Check if required content is provided
    if format_def["requires_content"]:
        content_field = format_def["content_field"]
        content = config.get(content_field, "")

        if not content:
            return {
                "valid": False,
                "error": (
                    f"Format '{format_type}' requires a '{content_field}' field in the config "
                    f"describing the content to test. Please add it."
                ),
                "format_def": format_def,
            }

        if len(str(content)) < 100:
            warnings.append(
                f"The '{content_field}' is very short ({len(str(content))} chars). "
                "Provide a detailed, structured description for realistic persona reactions."
            )

    return {
        "valid": True,
        "format_def": format_def,
        "warnings": warnings,
        "interviewer_prompt_extension": FORMAT_INTERVIEWER_PROMPTS.get(format_type, ""),
        "specific_metrics": format_def["specific_metrics"],
        "caveats": format_def["caveats"],
    }


def get_format_caveats(format_type: str) -> List[str]:
    """Get the format-specific caveats for the report."""
    format_def = EXPERIMENT_FORMATS.get(format_type, {})
    return format_def.get("caveats", [])


def generate_format_section(format_type: str) -> str:
    """Generate a Markdown section describing the experiment format and its limitations."""
    format_def = EXPERIMENT_FORMATS.get(format_type)
    if not format_def:
        return ""

    lines = [
        "### Experiment Format",
        "",
        f"**Format:** {format_def['name']}",
        "",
        format_def["description"],
        "",
    ]

    if format_def["specific_metrics"]:
        lines.append("**Format-Specific Metrics:**")
        for metric in format_def["specific_metrics"]:
            lines.append(f"- {metric.replace('_', ' ').title()}")
        lines.append("")

    if format_def["caveats"]:
        lines.append("**Format-Specific Limitations:**")
        for caveat in format_def["caveats"]:
            lines.append(f"- {caveat}")
        lines.append("")

    return "\n".join(lines)
