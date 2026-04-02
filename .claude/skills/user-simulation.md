---
name: user-simulation
description: Run an iterative, self-improving user simulation to test a product, agent, or GTM idea. Use when the user wants to simulate user/customer interactions, test assumptions, or generate a knowledge base for an agent.
---

# User Simulation Skill

This skill runs iterative, self-improving user simulations. **No API key required** when running inside Claude Code — Claude IS the LLM. The Python engines handle only computation: config validation, bias detection, statistical analysis, scoring.

## Two Modes

| Mode | Who does the LLM work? | API Key Required? | Best For |
|------|------------------------|-------------------|----------|
| **Claude Code (default)** | You (Claude) generate personas, run interviews, write analysis | **No** — you are the LLM | Interactive use, iteration, most users |
| **Standalone pipeline** | `python3 run.py` calls Anthropic/OpenAI APIs | Yes (`ANTHROPIC_API_KEY`) | Automated/CI, 100+ persona runs, batch jobs |

**Default to Claude Code mode.** Only suggest standalone mode if the user specifically needs large-scale parallel execution (100+ personas).

---

## How to Run a Simulation (Claude Code Mode)

### Step 1: Gather Context Conversationally

Ask the user what they want to test. Don't ask for everything at once — gather progressively across 3-5 exchanges.

**Data Gathering Checklist:**

| Input | Priority | What to Ask |
|---|---|---|
| **Product/Agent definition** | **Required** | "What are you testing? Describe the product in 2-3 sentences." |
| **Assumptions to test** | **Required** | "What's the riskiest assumption? What has to be true for this to work?" |
| **Real transcripts** | Critical | "Do you have any real sales calls, customer interviews, or chat logs? Even 2-3 dramatically improve quality." |
| **Customer list / CRM data** | High | "Can you describe your actual customers? Segments, sizes, industries?" |
| **Market research / world model** | High | "Any competitor info, market data, or industry research to ground this in?" |
| **Experiment format** | Medium | "How should the interaction happen: interview, focus group, webpage review, form test?" |

### Step 2: Create Config and Validate

Build a YAML config from what you gathered. Save it under `examples/`:

```yaml
product:
  name: "Product Name"
  description: "What it does"
  target_market: "Who it's for"
assumptions:
  - "Testable hypothesis 1"
  - "Testable hypothesis 2"
settings:
  persona_count: 20          # 10-30 is ideal for Claude Code mode
  interview_turns: 5
  interaction_context: warm_demo
  experiment_format: interview
context:
  world_model: "context/world_model.md"    # if user provided
  transcripts: "context/transcripts.md"    # if user provided
  customer_list: "context/customers.md"    # if user provided
```

**Validate and grade context quality** using the Python utilities:
```bash
python3 engines/sim_utils.py validate path/to/config.yaml
python3 engines/sim_utils.py context-quality path/to/config.yaml
```

**Context Quality Grades:**

| Grade | What Was Provided | Reliability |
|---|---|---|
| **A** | World model + transcripts + customer list | High — grounded in real data |
| **B** | World model + at least one of transcripts/customer list | Good — partially grounded |
| **C** | World model only, or transcripts + customer list | Moderate — significant estimation |
| **D** | One thin file, or no real data | Low — mostly LLM imagination |
| **F** | No context files at all | Very low — hypotheses only |

**If grade is D or F, warn the user** that results should be treated as directional hypotheses, not market evidence. Strongly encourage them to provide real transcripts.

### Step 3: Generate Personas (You Do This)

**You are the LLM.** Generate personas directly — do not shell out to Python for this.

For each archetype in the config, generate personas following this structure:

```json
{
  "name": "Full Name",
  "title": "Job Title",
  "company_type": "Type/size of company",
  "company_size": "Employee count or revenue",
  "industry": "Specific vertical",
  "region": "Geographic region",
  "years_experience": 12,
  "current_tools": "What they use today for this problem",
  "pain_points": ["Specific pain 1", "Specific pain 2"],
  "priorities": ["Priority 1", "Priority 2", "Priority 3"],
  "budget_sensitivity": "low|medium|high",
  "tech_sophistication": "low|medium|high",
  "personality_notes": "2-3 sentences on how they communicate and decide"
}
```

**Anti-sycophancy rules** (critical — follow these strictly):
- Only ~10% of personas should be "enthusiastic." ~40% should be skeptical or resistant.
- Each persona must have genuine, specific reasons for their attitude — not generic pushback.
- Include personas who would genuinely say "no" and mean it.
- Red Team archetype (10%) should be deeply skeptical, almost impossible to convince.

**After generating personas, assign simulation metadata** via Python:
```python
# For each persona, run this to assign disposition + skepticism score:
python3 -c "
import json, sys
sys.path.insert(0, '.')
from engines.sim_utils import assign_persona_metadata
persona = $PERSONA_JSON
archetype = $ARCHETYPE_JSON
result = assign_persona_metadata(persona, '$ARCHETYPE_KEY', archetype, $DISPOSITION_WEIGHTS, '$INTERACTION_CONTEXT')
print(json.dumps(result, indent=2))
"
```

Or batch them: save personas to a JSON file, then use the utility to enrich them.

### Step 4: Run Interviews (You Do This)

**You conduct the interviews directly.** For each persona, role-play both the interviewer and the persona.

**Interviewer rules:**
- Be a skilled but neutral researcher — do NOT lead the witness
- Stress-test positive signals: "You said you'd pay for this — what specifically would make you change your mind?"
- Probe behind surface answers: "You mentioned [X]. Can you walk me through the last time that happened?"
- Don't accept vague positivity — push for specifics
- If the persona's disposition is "resistant" or "skeptical," honor that throughout

**Persona rules:**
- Stay in character based on the persona definition AND their assigned disposition/skepticism score
- A persona with skepticism_score=9 should be very hard to convince
- A "resistant" persona should not suddenly become enthusiastic
- Use language and reasoning appropriate to the persona's background
- Reference their specific current_tools, pain_points, and priorities

**Interview format:**
```json
{
  "persona_id": "persona_name",
  "persona": { ... },
  "transcript": [
    {"role": "interviewer", "content": "..."},
    {"role": "persona", "content": "..."}
  ],
  "outcome": "interested|neutral|skeptical|rejected",
  "key_quotes": ["Notable quote 1", "Notable quote 2"],
  "objections_raised": ["Objection 1", "Objection 2"],
  "signals": {
    "purchase_intent": "none|low|medium|high",
    "would_recommend": true/false,
    "biggest_concern": "...",
    "most_valued_feature": "..."
  }
}
```

Run 5-turn interviews (or whatever `interview_turns` is set to). For 20 personas, you'll conduct 20 interviews.

### Step 5: Analyze and Audit

After all interviews are complete:

1. **Run bias audit** on the interview data:
```bash
python3 -c "
import json, sys
sys.path.insert(0, '.')
from engines.bias_detection import run_bias_audit, generate_bias_audit_section
interviews = json.load(open('path/to/interviews.json'))
audit = run_bias_audit(interviews)
print(json.dumps(audit, indent=2))
print('---')
print(generate_bias_audit_section(audit))
"
```

2. **Generate statistical appendix:**
```bash
python3 -c "
import json, sys
sys.path.insert(0, '.')
from engines.statistical_validation import generate_statistical_appendix
interviews = json.load(open('path/to/interviews.json'))
personas = json.load(open('path/to/personas.json'))
print(generate_statistical_appendix(interviews, personas))
"
```

3. **Write the report yourself.** You're better at synthesis than a templated engine. Include:
   - Executive summary
   - Key findings (with supporting quotes from interviews)
   - Assumption validation (confirmed / challenged / inconclusive for each)
   - Segment-level analysis (how different archetypes responded)
   - Bias audit results (paste from step 1)
   - Statistical appendix (paste from step 2)
   - Recommendations

4. **Save all outputs:**
```bash
python3 -c "
import json, sys
sys.path.insert(0, '.')
from engines.sim_utils import save_simulation_output
# Pass your data as arguments or read from temp files
save_simulation_output(
    output_dir='path/to/output',
    personas=json.load(open('personas.json')),
    interviews=json.load(open('interviews.json')),
    report_md=open('report.md').read(),
    transcripts_md=open('transcripts.md').read(),
    config=json.load(open('config.json')),
    bias_audit=json.load(open('bias_audit.json')),
    context_quality=json.load(open('context_quality.json')),
)
"
```

### Step 6: Iterate

Based on the results:

1. **Identify weakest areas** — Which assumptions got inconclusive results? Which archetypes behaved unrealistically?
2. **Check bias audit** — If disposition adherence is low, personas weren't staying in character. If sycophancy is high, you were too easy on them.
3. **Propose changes** — "The 'Data Operator' archetype wasn't skeptical enough. I'll regenerate those 4 personas with higher skepticism. Want me to re-run?"
4. **Track versions:**

| Version | Key Finding | Key Change |
|---|---|---|
| v1.0 | Skeptics too agreeable on pricing | Baseline |
| v1.1 | Better price objections, weak on competition | Increased skepticism scores |
| v1.2 | Realistic competitive pushback | Added competitor knowledge to personas |

---

## Scoring Engine (Optional, for Advanced Iteration)

For quantitative scoring across iterations, use the 7-dimension scoring engine:

| Dimension | What It Measures | Score |
|---|---|---|
| Objection Bypass Rate | % of objections where response led to positive next turn | 0.0-1.0 |
| Attribute Consistency | 1 - (contradictions / user turns) | 0.0-1.0 |
| Turns to Resolution | Normalized score (fewer turns = better) | 0.0-1.0 |
| Trust Signal Hit Rate | % of trust objections followed by trust signal | 0.0-1.0 |
| Cross-Sell Success Rate | % of cross-sell attempts with positive response | 0.0-1.0 |
| Conversion | Did conversation end in success? | 0.0 or 1.0 |
| Sentiment Velocity | Sentiment change from first half to second half | 0.0-1.0 |

**Note:** The scoring engine's `_analyze_turns()` function uses LLM calls. In Claude Code mode, you can score conversations qualitatively yourself, or use the standalone pipeline for automated scoring.

---

## Experiment Format Reference

| Format | Use When | Special Considerations |
|---|---|---|
| `interview` | Standard customer discovery | Default — no special setup |
| `focus_group` | Testing group dynamics, social proof | You play moderator + multiple personas simultaneously |
| `sales_sequence` | Multi-touch outreach optimization | Run as sequence of contacts over simulated time |
| `webpage_review` | Testing landing page messaging | Describe the page in config, personas react to it |
| `document_review` | Testing whitepaper/pitch deck | Describe the document, personas evaluate it |
| `form_test` | Testing signup/onboarding flow | Describe form steps, personas walk through them |
| `in_person_interview` | Simulating face-to-face | Add caveat: body language/rapport cannot be simulated |

---

## Standalone Pipeline Mode

For large-scale runs (100+ personas) or automation, use the full pipeline:

```bash
# Requires ANTHROPIC_API_KEY (for Claude models) or OPENAI_API_KEY (for others)
export ANTHROPIC_API_KEY="your-key"
python3 run.py path/to/config.yaml [--resume] [--log-level DEBUG]
```

This runs everything in parallel via the Python engines. Use this when you need scale, not when you need Claude Code's interactive experience.

---

## Output Files

| File | Description |
|---|---|
| `report.md` | Strategic report with bias audit and statistical appendix |
| `transcripts.md` | All interview transcripts |
| `personas.json` | Full persona definitions with metadata |
| `interviews.json` | Raw interview data |
| `bias_audit.json` | Disposition adherence and sycophancy detection |
| `context_quality.json` | Context quality grade and details |
| `scoring_results.json` | Per-dimension scoring (if scoring engine used) |
| `run_metadata.json` | Timestamp, config, quality grades |
