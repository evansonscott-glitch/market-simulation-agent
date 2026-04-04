"""
LDS Rumor Intelligence Agent — Data Models

Pydantic models for all data structures: announcements, rumors, Bayesian priors,
author records, and weekly digests.
"""
from datetime import datetime, date
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────

class AnnouncementCategory(str, Enum):
    TEMPLE_ANNOUNCEMENT = "temple_announcement"
    LEADERSHIP_CHANGE = "leadership_change"
    POLICY_UPDATE = "policy_update"
    ORGANIZATIONAL = "organizational"
    CULTURAL = "cultural"
    PROGRAM = "program"
    FINANCIAL = "financial"
    OTHER = "other"


class TempleSubcategory(str, Enum):
    NEW_TEMPLE = "new_temple"
    GROUNDBREAKING = "groundbreaking"
    DEDICATION = "dedication"
    RENOVATION = "renovation"
    REDEDICATION = "rededication"


class Specificity(str, Enum):
    EXACT_NAME_OR_LOCATION = "exact_name_or_location"
    CITY_LEVEL = "city_level"
    REGION_LEVEL = "region_level"
    CATEGORY_ONLY = "category_only"
    VAGUE = "vague"


class ClaimedSourceType(str, Enum):
    INSIDER_NAMED = "insider_named"
    INSIDER_FAMILY = "insider_family"
    INSIDER_ANONYMOUS = "insider_anonymous"
    SECONDHAND = "secondhand"
    SPECULATION = "speculation"
    PREDICTION = "prediction"


class LanguageConfidence(str, Enum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


class Falsifiability(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ResolutionStatus(str, Enum):
    CONFIRMED = "confirmed"
    PARTIALLY_CONFIRMED = "partially_confirmed"
    DENIED = "denied"
    UNRESOLVED = "unresolved"


class MatchQuality(str, Enum):
    EXACT = "exact"
    PARTIAL = "partial"
    RELATED = "related"
    NO_MATCH = "no_match"


class ConfidenceTier(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NOISE = "noise"


class SourcePlatform(str, Enum):
    REDDIT = "reddit"
    TWITTER = "twitter"
    BLOG = "blog"
    OTHER = "other"


# ──────────────────────────────────────────────
# Official Announcement Record
# ──────────────────────────────────────────────

class Location(BaseModel):
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None


class AnnouncementRecord(BaseModel):
    id: str = Field(..., description="Unique ID like 'ann-2025-042'")
    date: date
    category: AnnouncementCategory
    title: str
    summary: str
    source_url: str
    subcategory: Optional[str] = None
    location: Optional[Location] = None
    tags: List[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def id_format(cls, v: str) -> str:
        if not v.startswith("ann-"):
            raise ValueError("Announcement ID must start with 'ann-'")
        return v


# ──────────────────────────────────────────────
# Rumor Record
# ──────────────────────────────────────────────

class RumorFeatures(BaseModel):
    category: AnnouncementCategory
    specificity: Specificity
    claimed_source_type: ClaimedSourceType
    language_confidence: LanguageConfidence
    corroboration_count: int = Field(default=0, ge=0)
    corroborating_post_ids: List[str] = Field(default_factory=list)
    falsifiability: Falsifiability
    public_record_available: bool = False


class RumorResolution(BaseModel):
    status: ResolutionStatus = ResolutionStatus.UNRESOLVED
    matched_announcement_id: Optional[str] = None
    match_quality: Optional[MatchQuality] = None
    days_before_announcement: Optional[int] = None
    resolved_date: Optional[date] = None


class RumorRecord(BaseModel):
    id: str = Field(..., description="Unique ID like 'rum-2025-00381'")
    source_platform: SourcePlatform
    source_sub: Optional[str] = None
    source_url: str
    author: str
    post_date: date
    raw_text: str
    extracted_claim: str
    features: RumorFeatures
    resolution: RumorResolution = Field(default_factory=RumorResolution)

    @field_validator("id")
    @classmethod
    def id_format(cls, v: str) -> str:
        if not v.startswith("rum-"):
            raise ValueError("Rumor ID must start with 'rum-'")
        return v


# ──────────────────────────────────────────────
# Rumor Clusters
# ──────────────────────────────────────────────

class RumorCluster(BaseModel):
    cluster_id: str
    cluster_summary: str
    rumor_ids: List[str]
    independent_source_count: int = Field(ge=1)
    earliest_post_date: date
    resolution: RumorResolution = Field(default_factory=RumorResolution)


# ──────────────────────────────────────────────
# Bayesian Prior Tables
# ──────────────────────────────────────────────

class FeatureStats(BaseModel):
    base_rate: Optional[float] = None
    true_positive_rate: Optional[float] = None
    sample_size: int = 0
    likelihood_ratio: float = 1.0


class PriorTables(BaseModel):
    feature_priors: Dict[str, Dict[str, FeatureStats]] = Field(
        default_factory=dict,
        description="Nested dict: feature_dimension -> feature_value -> stats"
    )
    global_base_rate: float = Field(default=0.22, ge=0.0, le=1.0)
    last_updated: date = Field(default_factory=date.today)
    total_labeled_rumors: int = Field(default=0, ge=0)
    version: str = "v1.0"


# ──────────────────────────────────────────────
# Author Records
# ──────────────────────────────────────────────

class AuthorRecord(BaseModel):
    author_id: str
    platform: SourcePlatform = SourcePlatform.REDDIT
    correct_predictions: int = Field(default=0, ge=0)
    wrong_predictions: int = Field(default=0, ge=0)
    total_predictions: int = Field(default=0, ge=0)
    first_seen: date = Field(default_factory=date.today)
    last_seen: date = Field(default_factory=date.today)

    @property
    def track_record(self) -> str:
        if self.total_predictions == 0:
            return "no_history"
        ratio = self.correct_predictions / self.total_predictions
        if ratio >= 0.6:
            return "previously_correct"
        elif ratio <= 0.3:
            return "previously_wrong"
        return "mixed"


# ──────────────────────────────────────────────
# Weekly Digest
# ──────────────────────────────────────────────

class ScoredRumor(BaseModel):
    rumor_id: str
    cluster_summary: str
    score: float = Field(ge=0.0, le=1.0)
    confidence_tier: ConfidenceTier
    score_explanation: str
    sources: List[str] = Field(default_factory=list)
    post_count: int = Field(default=1, ge=1)


class ResolvedRumor(BaseModel):
    rumor_id: str
    original_score: float
    resolution: ResolutionStatus
    prior_update_applied: bool = False


class ModelStats(BaseModel):
    total_tracked: int = 0
    resolved_this_week: int = 0
    accuracy_last_30_days: Optional[float] = None
    prior_tables_version: str = "v1.0"


class DigestRecord(BaseModel):
    digest_id: str = Field(..., description="Like 'digest-2026-W14'")
    week_start: date
    week_end: date
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    new_rumors: List[ScoredRumor] = Field(default_factory=list)
    resolved_rumors: List[ResolvedRumor] = Field(default_factory=list)
    model_stats: ModelStats = Field(default_factory=ModelStats)


# ──────────────────────────────────────────────
# Calibration Report
# ──────────────────────────────────────────────

class DecileBucket(BaseModel):
    range_low: float
    range_high: float
    count: int
    actual_true_rate: float
    predicted_avg: float
    deviation: float


class CalibrationReport(BaseModel):
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    total_scored: int = 0
    total_resolved: int = 0
    deciles: List[DecileBucket] = Field(default_factory=list)
    overall_accuracy: Optional[float] = None
    needs_retrain: bool = False
    notes: List[str] = Field(default_factory=list)


# ──────────────────────────────────────────────
# Config Schema
# ──────────────────────────────────────────────

class RedditConfig(BaseModel):
    client_id: str = ""
    client_secret: str = ""
    user_agent: str = "lds-rumor-agent/1.0"
    subreddits: List[str] = Field(default_factory=lambda: [
        "latterdaysaints", "lds", "mormon", "exmormon", "temples"
    ])
    speculative_keywords: List[str] = Field(default_factory=lambda: [
        "I heard", "rumor", "prediction", "my bishop said",
        "my stake president", "someone at COB", "I bet they",
        "wouldn't be surprised", "anyone else hearing", "temple in",
        "going to announce", "new temple", "called as",
        "handbook change", "policy change", "I think they'll",
        "speculation", "inside source", "confirmed", "unconfirmed", "leaked",
    ])
    min_engagement_comments: int = Field(default=10, ge=0)


class EmailConfig(BaseModel):
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    sender_address: str = ""
    app_password: str = ""
    recipient: str = ""


class AgentConfig(BaseModel):
    """Top-level configuration for the LDS Rumor Agent."""
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"
    reddit: RedditConfig = Field(default_factory=RedditConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    newsroom_base_url: str = "https://newsroom.churchofjesuschrist.org"
    temples_url: str = "https://www.churchofjesuschrist.org/temples"
    data_dir: str = "data"
    lookback_months: int = Field(default=12, ge=1, le=36)
    batch_size: int = Field(default=50, ge=10, le=200)
