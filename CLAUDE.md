# CLAUDE.md — Context for Claude Code

## What This Repo Is

This is the Market Simulation Agent — an AI-powered tool that validates product assumptions through simulated customer interviews. It generates realistic buyer personas, conducts multi-turn interviews, and produces strategic reports with statistical validation and bias auditing.

## How to Use This Repo in Claude Code

### Primary Flow: The `/user-simulation` Skill

When a user wants to run a simulation, trigger the `user-simulation` skill defined in `skill/SKILL.md`. This walks through a 6-step iterative loop:

1. Gather context (transcripts, product definition, assumptions, market data)
2. Define the scoring function (7 code-based dimensions)
3. Run the simulation via `python3 run.py path/to/config.yaml`
4. Score and audit results (automatic: bias audit, statistical appendix, context quality grade)
5. Analyze gaps and revise inputs
6. Commit versioned improvements and repeat

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
run.py                             # Main pipeline runner (the single entry point)
core/conversation_engine.py        # 5-stage Socratic coaching flow
engines/
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
  llm_client.py                    # LLM wrapper with retry + rate limiting
  json_parser.py                   # Multi-strategy robust JSON parser
  checkpoint.py                    # Crash recovery via atomic writes
skill/
  SKILL.md                         # The user-simulation skill definition
  references/scoring_rubric.md     # Qualitative 1-5 rubric for manual calibration
```

## Running the Pipeline

```bash
# Full pipeline
python3 run.py path/to/config.yaml [--resume] [--log-level DEBUG]

# Requires: OPENAI_API_KEY or compatible API key set in environment
# Default model: gemini-2.5-flash (configurable in YAML)
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
  persona_count: 100        # 1-1000, default 100
  interview_turns: 5         # 1-20, default 5
  interaction_context: warm_demo  # warm_demo | cold_outreach | blended
  experiment_format: interview    # interview | focus_group | sales_sequence | webpage_review | document_review | form_test | in_person_interview
context:
  world_model: "path/to/world_model.md"
  transcripts: "path/to/transcripts.md"
  customer_list: "path/to/customers.md"
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
