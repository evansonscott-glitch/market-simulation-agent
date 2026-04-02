---
name: user-simulation
description: Run an iterative, self-improving user simulation to test a product, agent, or GTM idea. Use when the user wants to simulate user/customer interactions, test assumptions, or generate a knowledge base for an agent.
---

# User Simulation Skill

This skill enables Manus to run an iterative, self-improving user simulation loop. It orchestrates the Python simulation engines in this repository to test a product, agent, or go-to-market strategy against simulated user personas, score the results, and iteratively refine until the simulation realistically mirrors real-world behavior.

## Architecture

This skill is the **orchestration layer** for the simulation engines in this repository:

| Skill Step | Engine Used | File |
|---|---|---|
| Context gathering | Context Quality Engine | `engines/context_quality.py` |
| Scoring definition | Scoring Engine | `engines/scoring_engine.py` |
| World model | Research Engine | `engines/research_engine.py` |
| Persona generation | Persona Engine + Market Census | `engines/persona_engine.py`, `engines/market_census.py` |
| Interview execution | Interview Engine (or Focus Group / Temporal Sequence) | `engines/interview_engine.py`, `engines/focus_group.py`, `engines/temporal_sequence.py` |
| Scoring | Scoring Engine (code-based, 7 dimensions) | `engines/scoring_engine.py` |
| Bias audit | Bias Detection Engine | `engines/bias_detection.py` |
| Statistical validation | Statistical Validation Engine | `engines/statistical_validation.py` |
| Format-specific handling | Experiment Formats Engine | `engines/experiment_formats.py` |
| Analysis & report | Analysis Engine | `engines/analysis_engine.py` |
| Full pipeline | Main Runner | `run.py` |

**The skill defines the process. The engines provide the implementation.**

---

## Core Workflow

The simulation follows a six-step iterative loop:

1. **Define the World Model** — Gather context (transcripts, CRM data, product definition, goals, triggers, market research)
2. **Define the Scoring Function** — Establish a measurable rubric for what "better" looks like
3. **Run the Simulation** — Execute the pipeline via `run.py` or individual engines
4. **Score the Results** — Evaluate each conversation against the rubric using `engines/scoring_engine.py`
5. **Revise and Refine** — Analyze gaps, update personas/playbooks/triggers
6. **Commit and Iterate** — Version the knowledge base and repeat

---

## Step 1: Define the World Model (Input Gathering)

Before running any simulation, gather context using a conversational approach. Do NOT ask for everything at once — gather progressively.

### Data Gathering Checklist

| Input | Description | Priority | Quality Impact |
|---|---|---|---|
| **Real Transcripts** | Actual call recordings, SMS threads, or email chains with real users/customers. | **Critical** | Ground truth. Without this, context quality grade will be D or F. |
| **CRM Data / Customer List** | Customer relationship data (segments, job values, conversion rates, service history). | High | Enables calibrated personas that match real buyer distribution. |
| **The Product/Agent** | Clear definition of what is being simulated (the product, AI agent, sales rep). | **Required** | Defines one side of the conversation. Must be specific (>10 chars). |
| **The Goal** | Desired outcome (book appointment, make purchase, resolve ticket). | **Required** | Defines the "win" condition for scoring. |
| **Triggers** | Events that initiate interaction (signup, storm, competitor switch). | High | Defines conversation context. Maps to `interaction_context` in config. |
| **Market Research / World Model** | Research on target audience, market dynamics, competitive landscape. | High | Grounds personas in reality. If missing, auto-generated (lower quality). |
| **Assumptions to Test** | Specific, testable hypotheses about the market. | **Required** | At least one assumption OR question is required by config validation. |
| **Experiment Format** | How the interaction happens: interview, focus group, webpage review, form test, etc. | Medium | Determines which engine to use and what metrics to track. |

### Context Quality Grades

The `engines/context_quality.py` module grades context A-F. This grade appears in the report header:

| Grade | What Was Provided | Reliability |
|---|---|---|
| **A** | World model + transcripts + customer list (all substantive) | High — findings are grounded in real data |
| **B** | World model + at least one of transcripts/customer list | Good — partially grounded |
| **C** | World model only, or transcripts + customer list | Moderate — significant LLM estimation |
| **D** | One thin file, or auto-generated world model only | Low — mostly LLM imagination |
| **F** | No context files at all | Very low — treat as hypotheses only |

**If real transcripts are not available, you MUST inform the user that the simulation will have lower fidelity (grade D or below) and results should be treated as directional hypotheses, not market evidence.**

---

## Step 2: Define the Scoring Function

The scoring engine (`engines/scoring_engine.py`) uses 7 code-based, deterministic dimensions:

| # | Dimension | What It Measures | Score Type |
|---|---|---|---|
| 1 | **Objection Bypass Rate** | % of objections where the next user turn is positive/neutral | 0.0-1.0 |
| 2 | **Attribute Consistency** | 1.0 minus (contradictions / user turns) | 0.0-1.0 |
| 3 | **Turns to Resolution** | Normalized score based on turn count (fewer = better) | 0.0-1.0 |
| 4 | **Trust Signal Hit Rate** | % of trust objections followed by a trust signal within 2 turns | 0.0-1.0 |
| 5 | **Cross-Sell Success Rate** | % of cross-sell attempts getting positive reaction | 0.0-1.0 |
| 6 | **Conversion** | Did the conversation end in success? | 0.0 or 1.0 |
| 7 | **Sentiment Velocity** | Change in sentiment from first half to second half | 0.0-1.0 |

Default weights:
```
objection_bypass_rate: 0.20
attribute_consistency: 0.15
turns_to_resolution:  0.10
trust_signal_hit_rate: 0.15
cross_sell_success_rate: 0.10
conversion: 0.15
sentiment_velocity: 0.15
```

Propose the rubric to the user and get buy-in before proceeding. If they want to adjust weights or add dimensions, update the weights dict passed to `score_simulation_batch()`.

### Qualitative Rubric (for manual review)

For manual spot-checks during iteration, use `references/scoring_rubric.md` which provides the 1-5 scale descriptions for human evaluation. The code-based scoring is primary; the qualitative rubric is for calibration.

---

## Step 3: Run the Simulation

### Option A: Full Pipeline (Recommended)

Run the complete pipeline via CLI:
```bash
python3 run.py path/to/config.yaml [--resume] [--log-level DEBUG]
```

This executes: config validation → world model → persona generation → interviews → analysis → bias audit → statistical appendix → report.

### Option B: Individual Engines

For iteration on specific stages:
```python
from engines.persona_engine import generate_personas
from engines.interview_engine import run_interviews
from engines.scoring_engine import score_simulation_batch
from engines.analysis_engine import analyze_interviews
```

### Experiment Format Selection

Set `experiment_format` in config to match the test type:

| Format | Use When | Engine |
|---|---|---|
| `interview` | Standard customer discovery | `interview_engine.py` |
| `focus_group` | Testing group dynamics, social proof | `focus_group.py` |
| `sales_sequence` | Multi-touch outreach optimization | `temporal_sequence.py` |
| `webpage_review` | Testing landing page messaging | `interview_engine.py` + format prompts |
| `document_review` | Testing whitepaper/pitch deck content | `interview_engine.py` + format prompts |
| `form_test` | Testing signup/onboarding flow | `interview_engine.py` + format prompts |
| `in_person_interview` | Simulating in-person with caveats | `interview_engine.py` + format prompts |

### Sample Size Guidance

The `engines/statistical_validation.py` module recommends minimum sample sizes:
- **Directional insights**: 15+ per segment (minimum)
- **Statistically rigorous**: Use `recommend_sample_size(num_segments)` to calculate
- If any segment has < 20 personas, sub-group findings are flagged as unreliable

---

## Step 4: Score the Results

After the simulation run, score every conversation:

```python
from engines.scoring_engine import score_simulation_batch, generate_score_report

scoring_result = score_simulation_batch(interviews, model="gemini-2.5-flash")
report_path = generate_score_report(scoring_result, output_dir)
```

This produces:
- Per-conversation scores across all 7 dimensions
- Aggregate scores with mean, min, max, std dev
- Per-archetype breakdown
- Weakest/strongest dimension identification
- `scoring_report.md` and `scoring_results.json`

### Automated Quality Checks

The pipeline also runs:
- **Bias audit** (`engines/bias_detection.py`): Disposition adherence, sycophancy detection
- **Statistical validation** (`engines/statistical_validation.py`): Confidence intervals, sample adequacy
- **Context quality** (`engines/context_quality.py`): A-F grade on input quality

---

## Step 5: Revise and Refine

Analyze the scoring results to identify the biggest gaps:

1. **Identify the lowest-scoring dimensions.** If "Attribute Consistency" is low, persona definitions need work. If "Objection Bypass Rate" is low, the agent playbook needs revision.
2. **Check the bias audit.** If disposition adherence is low, personas aren't behaving as assigned. If sycophancy rate is > 20%, anti-sycophancy prompts need strengthening.
3. **Check segment differences.** Use the statistical validation to see if differences between archetypes are real or noise.
4. **Formulate a hypothesis.** Example: "The 'Retiree' persona is not price-sensitive enough. I will revise the persona to include stronger fixed-income budget constraints."
5. **Revise the inputs.** Update persona definitions, agent playbooks, trigger framing, or archetype weights in the YAML config.

---

## Step 6: Commit and Iterate

Commit the revised inputs and results as a new version.

### Versioning

- Use a simple version number (e.g., v1.1, v1.2)
- Include a plain-language summary of what changed and why
- Example: `v1.2 — Increased price sensitivity in Retiree persona to better match real-world budget objections. Attribute Consistency improved from 0.62 to 0.78.`

### The Loop

After committing, repeat from Step 3. Track score progression across iterations:

| Version | Composite Score | Weakest Dimension | Key Change |
|---|---|---|---|
| v1.0 | 0.54 | Objection Bypass (0.31) | Baseline |
| v1.1 | 0.61 | Trust Signal Hit Rate (0.38) | Revised objection playbook |
| v1.2 | 0.68 | Persona Consistency (0.55) | Added trust signal scripts |
| v1.3 | 0.74 | — | Refined persona definitions |

The goal is to see scores improve with each iteration, indicating the simulation is becoming a more accurate proxy for reality.

---

## Output Files

Each simulation run produces:

| File | Description |
|---|---|
| `report.md` | McKinsey-grade strategic report with bias audit and statistical appendix |
| `transcripts.md` | All interview transcripts in readable format |
| `personas.json` | Full persona definitions with metadata |
| `interviews.json` | Raw interview data |
| `quantitative_summary.json` | Numerical scores and metrics |
| `audience_summary.md` | Demographic/archetype distribution |
| `bias_audit.json` | Disposition adherence and sycophancy detection results |
| `context_quality.json` | Context quality grade and details |
| `scoring_report.md` | Per-dimension scoring breakdown (if scoring engine used) |
| `scoring_results.json` | Raw scoring data (if scoring engine used) |
| `run_metadata.json` | Timestamp, config, runtime stats, quality grades |
| `simulation.log` | Structured log with all debug info |
