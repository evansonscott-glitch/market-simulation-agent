# CLAUDE.md — Context for Claude Code

## What This Repo Is

This is the Market Simulation Agent — an AI-powered tool that validates product assumptions through simulated customer interviews. It generates realistic buyer personas, conducts multi-turn interviews, and produces strategic reports with statistical validation and bias auditing.

## How to Use This Repo in Claude Code

### No API Key Required

When running inside Claude Code, **you ARE the LLM**. You generate personas, conduct interviews, and write analysis directly. The Python engines handle only computation — config validation, bias detection, statistical analysis. No separate API key needed.

### Primary Flow: The `/user-simulation` Skill

When a user wants to run a simulation, trigger the `user-simulation` skill defined in `skill/SKILL.md`. This walks through a 6-step iterative loop:

1. Gather context (transcripts, product definition, assumptions, market data)
2. Create and validate a YAML config
3. Generate personas and conduct interviews (you do this — you are the LLM)
4. Run bias audit + statistical validation (Python utilities)
5. Write the analysis report
6. Iterate based on results

### When to Trigger the Skill

Trigger `/user-simulation` when the user says anything like:
- "I want to simulate/test customer reactions"
- "Can you validate my product assumptions?"
- "Run a market simulation"
- "Test my landing page / pitch deck / signup flow with simulated users"
- "Generate personas and interview them"
- "I want to see how customers would respond to..."

### When NOT to Trigger the Skill

- User asking about the code architecture → just read and explain
- User wanting to fix a bug → normal code editing
- User asking about the review findings → reference `REVIEW.md`

## Key Architecture

```
config.py                          # YAML config loading + Pydantic validation
run.py                             # Standalone pipeline runner (needs API key)
core/conversation_engine.py        # 5-stage Socratic coaching flow (for Slack/CLI/web)
engines/
  sim_utils.py                     # Non-LLM utilities for Claude Code skill flow
  persona_engine.py                # Stratified persona generation with anti-sycophancy
  interview_engine.py              # Async multi-turn interviews with checkpointing
  analysis_engine.py               # Insight extraction + McKinsey-grade reports
  scoring_engine.py                # 7-dimension code-based conversation scoring
  research_engine.py               # Auto world model generation
  market_census.py                 # Statistically valid sample frame generator
  focus_group.py                   # Agent-to-agent focus group discussions
  temporal_sequence.py             # Multi-touch sales sequence simulation
  post_sim_chat.py                 # Follow-up chat with personas after simulation
  context_quality.py               # A-F context quality grading
  statistical_validation.py        # Confidence intervals, sample size, significance tests
  bias_detection.py                # Disposition adherence + sycophancy detection
  experiment_formats.py            # Format-specific prompts/metrics (webpage, PDF, form, etc.)
  llm_client.py                    # LLM wrapper with retry + rate limiting (standalone mode)
  json_parser.py                   # Multi-strategy robust JSON parser
  checkpoint.py                    # Crash recovery via atomic writes
skill/
  SKILL.md                         # The user-simulation skill definition
  references/scoring_rubric.md     # Qualitative 1-5 rubric for manual calibration
```

### Two Modes

| Mode | LLM Work Done By | API Key? | Use Case |
|------|-------------------|----------|----------|
| **Claude Code skill** | You (Claude) | No | Default. Interactive, iterative. |
| **Standalone pipeline** | `python3 run.py` via API | Yes (`ANTHROPIC_API_KEY`) | Large-scale runs, CI, automation. |

## Running the Standalone Pipeline

```bash
# Only needed for standalone mode (100+ persona runs, automation)
export ANTHROPIC_API_KEY="your-key"
python3 run.py path/to/config.yaml [--resume] [--log-level DEBUG]

# Default model: claude-sonnet-4-6
# For OpenAI/Gemini models: set OPENAI_API_KEY and specify model in YAML
```

## Quick Utilities (for Claude Code skill flow)

```bash
# Validate a config
python3 engines/sim_utils.py validate path/to/config.yaml

# Grade context quality
python3 engines/sim_utils.py context-quality path/to/config.yaml

# Check sample size adequacy
python3 engines/sim_utils.py sample-check 30 6
```

## Config Format

Configs are YAML files. Minimum required:
```yaml
product:
  name: "Product Name"
  description: "What the product does (10+ chars)"
  target_market: "Who it's for (10+ chars)"
assumptions:
  - "At least one testable assumption"
```

Optional but impactful:
```yaml
settings:
  persona_count: 20          # 10-30 for Claude Code mode, up to 1000 for standalone
  interview_turns: 5         # 1-20, default 5
  interaction_context: warm_demo  # warm_demo | cold_outreach | blended
  experiment_format: interview    # interview | focus_group | sales_sequence | webpage_review | document_review | form_test | in_person_interview
context:
  world_model: "path/to/world_model.md"
  transcripts: "path/to/transcripts.md"
  customer_list: "path/to/customers.md"
  webpage_url: "https://..."    # for webpage_review — Claude fetches it directly
  form_url: "https://..."       # for form_test
  document_url: "https://..."   # for document_review
```

## Context Quality Matters

The simulation quality depends heavily on what context the user provides:
- **Grade A**: world model + transcripts + customer list → high reliability
- **Grade F**: no context files → treat as hypotheses only

Always ask users for real transcripts and customer data. Even 2-3 real conversations dramatically improve output quality.

## Output

Each run produces files in a timestamped output directory:
- `report.md` — Strategic report with bias audit and statistical appendix
- `transcripts.md` — All interview transcripts
- `personas.json`, `interviews.json` — Raw data
- `bias_audit.json`, `context_quality.json` — Quality metrics
- `scoring_report.md`, `scoring_results.json` — Scoring (if scoring engine used)
- `run_metadata.json` — Config snapshot with quality grades
