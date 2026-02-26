"""
Philo Ventures Market Simulator — Configuration Loader

Loads simulation parameters from a YAML config file.
Every simulation run is defined by a single YAML file that specifies:
  - The product being tested
  - The target market
  - The assumptions or questions to validate
  - Buyer archetypes (or defaults)
  - Context files (transcripts, customer lists, world model)
"""
import os
import yaml
from typing import Dict, Any, Optional

# ── Global Defaults ──
DEFAULTS = {
    "llm_model": os.getenv("PV_LLM_MODEL", "gemini-2.5-flash"),
    "persona_count": 100,
    "interview_turns": 5,
    "interaction_context": "warm_demo",  # warm_demo | cold_outreach | blended
    "persona_concurrency": 5,
    "interview_concurrency": 10,
    "log_level": os.getenv("PV_LOG_LEVEL", "INFO"),
}

# ── Default Archetypes ──
# These are general-purpose B2B SaaS buyer archetypes.
# They can be overridden or extended in the YAML config.
DEFAULT_ARCHETYPES = {
    "data_hungry_operator": {
        "name": "The Data-Hungry Operator",
        "description": (
            "Sophisticated, analytical, and skeptical. Already has existing scorecards, KPIs, "
            "and analytics processes. Evaluates new tools on whether the data is better than "
            "what they already have. Asks specific technical questions about methodology."
        ),
        "behaviors": [
            "Immediately questions methodology and data accuracy",
            "Compares the tool's output to their own internal numbers",
            "Requests export capabilities and raw data access",
            "Evaluates based on accuracy and depth, not polish",
        ],
        "buying_triggers": [
            "Proof that the tool is more accurate than what they can build themselves",
            "Time savings on manual analytics work",
            "Access to benchmarking data they can't get alone",
        ],
        "common_objections": [
            "Our internal data already tells us this",
            "How do I know your methodology is sound?",
            "I need to verify these numbers against our own",
        ],
        "skepticism_range": [6, 9],
        "typical_weight": 0.15,
    },
    "overwhelmed_founder": {
        "name": "The Overwhelmed Founder",
        "description": (
            "Resource-constrained and wearing many hats. Knows the problem matters but doesn't "
            "have the bandwidth to address it systematically. Evaluates new tools against doing "
            "nothing. Wants to be told what to do, not given data to interpret."
        ),
        "behaviors": [
            "Asks 'what does this mean?' more than 'how does this work?'",
            "Gets excited about features that remove manual work",
            "Makes decisions quickly based on gut and trust",
            "Responds strongly to competitive benchmarking",
        ],
        "buying_triggers": [
            "Feeling that someone understands their problem",
            "AI summaries and automated insights",
            "Seeing their numbers vs. industry averages",
        ],
        "common_objections": [
            "This seems complicated — do I need a data person?",
            "I'm not sure we're big enough to need this yet",
            "I don't have time to learn another tool right now",
        ],
        "skepticism_range": [3, 6],
        "typical_weight": 0.25,
    },
    "automation_first_buyer": {
        "name": "The Automation-First Buyer",
        "description": (
            "Doesn't want visibility — wants action. Defines value as actual execution, not "
            "flagging or alerting. Wants set-and-forget automation. Often technically sophisticated."
        ),
        "behaviors": [
            "Frames everything in terms of automation and workflow triggers",
            "Asks 'does it actually do the work, or just tell me what to do?'",
            "Compares to their own custom-built systems",
            "Wants integration with existing workflow tools",
        ],
        "buying_triggers": [
            "When the tool can actually execute actions, not just recommend them",
            "Integration with their existing tools",
            "Autopilot concept — flip a switch, actions fire",
        ],
        "common_objections": [
            "Does this actually do the work or just flag things?",
            "We already built something that does part of this",
            "I need automation, not another dashboard",
        ],
        "skepticism_range": [5, 8],
        "typical_weight": 0.15,
    },
    "competitive_evaluator": {
        "name": "The Competitive Evaluator",
        "description": (
            "Actively comparing alternatives. Has done research, may already use a competing "
            "product. Wants clear differentiation and ROI justification. Negotiates on price."
        ),
        "behaviors": [
            "Directly compares features to competitors",
            "Negotiates on price",
            "Wants trial periods and flexible terms",
            "Needs to present to a decision-maker",
        ],
        "buying_triggers": [
            "Clear differentiation from what they already have",
            "Compelling ROI case with specific numbers",
            "Flexible pricing",
        ],
        "common_objections": [
            "How is this different from [competitor]?",
            "We already use [alternative] — why switch?",
            "Can we do a trial before committing?",
        ],
        "skepticism_range": [6, 9],
        "typical_weight": 0.15,
    },
    "strategic_enterprise": {
        "name": "The Strategic Enterprise",
        "description": (
            "Large, sophisticated organization. Not buying a product — evaluating a partner. "
            "Thinks in terms of strategic gaps, not feature checklists. Long decision timeline."
        ),
        "behaviors": [
            "Evaluates technical depth, not just features",
            "Thinks in terms of strategic gaps",
            "Willing to share data for a proof of concept",
            "Decision timeline is long — months, not days",
        ],
        "buying_triggers": [
            "Filling gaps they don't have time to build internally",
            "Potential for a deeper strategic partnership",
        ],
        "common_objections": [
            "We've already built most of this internally",
            "This is interesting but not a priority right now",
            "We'd need to see this run on our data first",
        ],
        "skepticism_range": [7, 10],
        "typical_weight": 0.10,
    },
    "red_team_skeptic": {
        "name": "The Red Team Skeptic",
        "description": (
            "Deeply skeptical of new tools. May have been burned by a previous vendor. "
            "Represents the hardest 'no' in the market. Their feedback reveals the strongest "
            "objections and the real barriers to adoption."
        ),
        "behaviors": [
            "Immediately challenges the premise",
            "Questions whether the technology actually works",
            "Raises data privacy and security concerns",
            "Points out they've survived fine without this tool",
            "Compares the cost to hiring a person",
        ],
        "buying_triggers": [
            "Almost nothing — they need overwhelming evidence",
            "A free trial with zero risk",
            "A trusted peer telling them it changed their business",
        ],
        "common_objections": [
            "We've been doing fine without this for years",
            "I don't trust AI to understand my business better than I do",
            "This sounds like a solution looking for a problem",
            "I'd rather hire someone than pay for another subscription",
        ],
        "skepticism_range": [8, 10],
        "typical_weight": 0.10,
    },
}

# ── Default Disposition Weights ──
DEFAULT_DISPOSITION_WEIGHTS = {
    "cold_outreach": {
        "enthusiastic": 0.05, "open": 0.12, "cautious": 0.30,
        "skeptical": 0.33, "resistant": 0.20,
    },
    "warm_demo": {
        "enthusiastic": 0.12, "open": 0.25, "cautious": 0.30,
        "skeptical": 0.23, "resistant": 0.10,
    },
    "blended": {
        "enthusiastic": 0.10, "open": 0.20, "cautious": 0.30,
        "skeptical": 0.27, "resistant": 0.13,
    },
}


def load_config(config_path: str) -> Dict[str, Any]:
    """
    Load a simulation config from a YAML file and merge with defaults.
    Returns a fully-resolved config dict ready for the simulation runner.
    """
    with open(config_path, "r") as f:
        user_config = yaml.safe_load(f)

    # Resolve base directory relative to the config file
    config_dir = os.path.dirname(os.path.abspath(config_path))

    # Build the resolved config
    config = {
        # ── Product Definition ──
        "product_name": user_config["product"]["name"],
        "product_description": user_config["product"]["description"],
        "target_market": user_config["product"]["target_market"],

        # ── What to Test ──
        "assumptions": user_config.get("assumptions", []),
        "questions": user_config.get("questions", []),

        # ── Simulation Parameters ──
        "llm_model": user_config.get("settings", {}).get("llm_model", DEFAULTS["llm_model"]),
        "persona_count": user_config.get("settings", {}).get("persona_count", DEFAULTS["persona_count"]),
        "interview_turns": user_config.get("settings", {}).get("interview_turns", DEFAULTS["interview_turns"]),
        "interaction_context": user_config.get("settings", {}).get("interaction_context", DEFAULTS["interaction_context"]),
        "persona_concurrency": user_config.get("settings", {}).get("persona_concurrency", DEFAULTS["persona_concurrency"]),
        "interview_concurrency": user_config.get("settings", {}).get("interview_concurrency", DEFAULTS["interview_concurrency"]),

        # ── Archetypes ──
        "archetypes": user_config.get("archetypes", DEFAULT_ARCHETYPES),
        "disposition_weights": user_config.get("disposition_weights", DEFAULT_DISPOSITION_WEIGHTS),

        # ── Context Files ──
        "context_dir": config_dir,
        "world_model_path": None,
        "transcripts_path": None,
        "customer_list_path": None,

        # ── Output ──
        "output_dir": user_config.get("output_dir", os.path.join(config_dir, "output")),
    }

    # Resolve context file paths
    context = user_config.get("context", {})
    if context.get("world_model"):
        config["world_model_path"] = os.path.join(config_dir, context["world_model"])
    if context.get("transcripts"):
        config["transcripts_path"] = os.path.join(config_dir, context["transcripts"])
    if context.get("customer_list"):
        config["customer_list_path"] = os.path.join(config_dir, context["customer_list"])

    return config


def load_context_file(path: Optional[str]) -> str:
    """Load a context file and return its contents, or empty string if not found."""
    if path and os.path.exists(path):
        with open(path, "r") as f:
            return f.read()
    return ""
