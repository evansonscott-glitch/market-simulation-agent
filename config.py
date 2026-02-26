"""
Philo Ventures Market Simulator — Configuration Loader & Validator

Loads simulation parameters from a YAML config file and validates them
using Pydantic models. Provides clear, actionable error messages when
config is invalid.

Every simulation run is defined by a single YAML file that specifies:
  - The product being tested
  - The target market
  - The assumptions or questions to validate
  - Buyer archetypes (or defaults)
  - Context files (transcripts, customer lists, world model)
"""
import os
import yaml
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field, field_validator, model_validator

from engines.logging_config import get_logger

logger = get_logger("config")


# ──────────────────────────────────────────────
# Pydantic Validation Models
# ──────────────────────────────────────────────

class ProductConfig(BaseModel):
    """Validates the product section of the config."""
    name: str = Field(..., min_length=1, description="Product name")
    description: str = Field(..., min_length=10, description="Product description")
    target_market: str = Field(..., min_length=10, description="Target market description")

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Product name cannot be empty or whitespace")
        return v.strip()


class SettingsConfig(BaseModel):
    """Validates simulation settings."""
    llm_model: str = Field(default="gemini-2.5-flash", description="LLM model to use")
    persona_count: int = Field(default=100, ge=1, le=1000, description="Number of personas to generate")
    interview_turns: int = Field(default=5, ge=1, le=20, description="Number of interview turns")
    interaction_context: str = Field(default="warm_demo", description="Interaction context type")
    persona_concurrency: int = Field(default=5, ge=1, le=50, description="Max concurrent persona generation calls")
    interview_concurrency: int = Field(default=10, ge=1, le=50, description="Max concurrent interviews")

    @field_validator("interaction_context")
    @classmethod
    def valid_interaction_context(cls, v: str) -> str:
        allowed = {"warm_demo", "cold_outreach", "blended"}
        if v not in allowed:
            raise ValueError(
                f"interaction_context must be one of {allowed}, got '{v}'"
            )
        return v

    @field_validator("llm_model")
    @classmethod
    def valid_model(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("llm_model cannot be empty")
        return v.strip()


class ContextConfig(BaseModel):
    """Validates context file references."""
    world_model: Optional[str] = Field(default=None, description="Path to world model file")
    transcripts: Optional[str] = Field(default=None, description="Path to transcripts file")
    customer_list: Optional[str] = Field(default=None, description="Path to customer list file")


class ArchetypeConfig(BaseModel):
    """Validates a single archetype definition."""
    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=10)
    behaviors: List[str] = Field(default_factory=list)
    buying_triggers: List[str] = Field(default_factory=list)
    common_objections: List[str] = Field(default_factory=list)
    skepticism_range: Tuple[int, int] = Field(default=(4, 7))
    typical_weight: float = Field(default=0.1, ge=0.0, le=1.0)

    @field_validator("skepticism_range")
    @classmethod
    def valid_skepticism_range(cls, v):
        if isinstance(v, (list, tuple)) and len(v) == 2:
            low, high = v
            if not (1 <= low <= 10 and 1 <= high <= 10 and low <= high):
                raise ValueError(
                    f"skepticism_range must be [low, high] where 1 <= low <= high <= 10, got {v}"
                )
            return (low, high)
        raise ValueError(f"skepticism_range must be a list/tuple of 2 ints, got {v}")


class SimulationConfig(BaseModel):
    """Top-level config validation."""
    product: ProductConfig
    assumptions: List[str] = Field(default_factory=list)
    questions: List[str] = Field(default_factory=list)
    settings: SettingsConfig = Field(default_factory=SettingsConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    archetypes: Optional[Dict[str, Any]] = Field(default=None)
    disposition_weights: Optional[Dict[str, Any]] = Field(default=None)
    output_dir: str = Field(default="output")

    @model_validator(mode="after")
    def must_have_assumptions_or_questions(self):
        if not self.assumptions and not self.questions:
            raise ValueError(
                "Config must include at least one 'assumption' or 'question' to test. "
                "Add an 'assumptions' list or 'questions' list to your config."
            )
        return self


class ConfigValidationError(Exception):
    """Raised when config validation fails. Contains user-friendly error messages."""

    def __init__(self, errors: List[str], config_path: str):
        self.errors = errors
        self.config_path = config_path
        error_list = "\n  - ".join(errors)
        super().__init__(
            f"Config validation failed for '{config_path}':\n  - {error_list}"
        )


# ──────────────────────────────────────────────
# Global Defaults
# ──────────────────────────────────────────────

DEFAULTS = {
    "llm_model": os.getenv("PV_LLM_MODEL", "gemini-2.5-flash"),
    "persona_count": 100,
    "interview_turns": 5,
    "interaction_context": "warm_demo",
    "persona_concurrency": 5,
    "interview_concurrency": 10,
    "log_level": os.getenv("PV_LOG_LEVEL", "INFO"),
}

# ── Default Archetypes ──
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


# ──────────────────────────────────────────────
# Config Loading & Validation
# ──────────────────────────────────────────────

def validate_config(config_path: str, raw_config: Dict[str, Any]) -> SimulationConfig:
    """
    Validate a raw YAML config dict using Pydantic models.

    Args:
        config_path: Path to the config file (for error messages).
        raw_config: The raw dict loaded from YAML.

    Returns:
        A validated SimulationConfig instance.

    Raises:
        ConfigValidationError: If validation fails, with user-friendly error messages.
    """
    try:
        return SimulationConfig(**raw_config)
    except Exception as e:
        # Extract user-friendly error messages from Pydantic
        errors = []
        if hasattr(e, "errors"):
            for err in e.errors():
                loc = " → ".join(str(x) for x in err.get("loc", []))
                msg = err.get("msg", str(err))
                errors.append(f"{loc}: {msg}")
        else:
            errors.append(str(e))

        raise ConfigValidationError(errors, config_path) from e


def load_config(config_path: str) -> Dict[str, Any]:
    """
    Load a simulation config from a YAML file, validate it, and merge with defaults.

    Args:
        config_path: Path to the YAML config file.

    Returns:
        A fully-resolved config dict ready for the simulation runner.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        ConfigValidationError: If the config is invalid.
        yaml.YAMLError: If the YAML is malformed.
    """
    # Check file exists
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    # Load YAML
    logger.info("Loading config from: %s", config_path)
    try:
        with open(config_path, "r") as f:
            user_config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.error("Failed to parse YAML config: %s", e)
        raise

    if not user_config or not isinstance(user_config, dict):
        raise ConfigValidationError(
            ["Config file is empty or not a valid YAML dictionary"],
            config_path,
        )

    # Validate with Pydantic
    validated = validate_config(config_path, user_config)
    logger.info("Config validation passed")

    # Resolve base directory relative to the config file
    config_dir = os.path.dirname(os.path.abspath(config_path))

    # Build the resolved config dict (engines expect this format)
    config = {
        # ── Product Definition ──
        "product_name": validated.product.name,
        "product_description": validated.product.description,
        "target_market": validated.product.target_market,

        # ── What to Test ──
        "assumptions": validated.assumptions,
        "questions": validated.questions,

        # ── Simulation Parameters ──
        "llm_model": validated.settings.llm_model,
        "persona_count": validated.settings.persona_count,
        "interview_turns": validated.settings.interview_turns,
        "interaction_context": validated.settings.interaction_context,
        "persona_concurrency": validated.settings.persona_concurrency,
        "interview_concurrency": validated.settings.interview_concurrency,

        # ── Archetypes ──
        "archetypes": validated.archetypes or DEFAULT_ARCHETYPES,
        "disposition_weights": validated.disposition_weights or DEFAULT_DISPOSITION_WEIGHTS,

        # ── Context Files ──
        "context_dir": config_dir,
        "world_model_path": None,
        "transcripts_path": None,
        "customer_list_path": None,

        # ── Output ──
        "output_dir": validated.output_dir if os.path.isabs(validated.output_dir)
                      else os.path.join(config_dir, validated.output_dir),
    }

    # Resolve context file paths and verify they exist
    if validated.context.world_model:
        path = os.path.join(config_dir, validated.context.world_model)
        if not os.path.exists(path):
            logger.warning("World model file not found: %s (will auto-generate)", path)
        else:
            config["world_model_path"] = path

    if validated.context.transcripts:
        path = os.path.join(config_dir, validated.context.transcripts)
        if not os.path.exists(path):
            logger.warning("Transcripts file not found: %s (will proceed without)", path)
        else:
            config["transcripts_path"] = path

    if validated.context.customer_list:
        path = os.path.join(config_dir, validated.context.customer_list)
        if not os.path.exists(path):
            logger.warning("Customer list file not found: %s (will proceed without)", path)
        else:
            config["customer_list_path"] = path

    logger.info(
        "Config loaded: product=%s, personas=%d, turns=%d, model=%s",
        config["product_name"],
        config["persona_count"],
        config["interview_turns"],
        config["llm_model"],
    )

    return config


def load_context_file(path: Optional[str]) -> str:
    """
    Load a context file and return its contents, or empty string if not found.

    Args:
        path: Path to the context file, or None.

    Returns:
        File contents as string, or empty string.
    """
    if not path:
        return ""

    if not os.path.exists(path):
        logger.warning("Context file not found: %s", path)
        return ""

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        logger.debug("Loaded context file: %s (%d chars)", path, len(content))
        return content
    except Exception as e:
        logger.error("Failed to read context file %s: %s", path, e)
        return ""
