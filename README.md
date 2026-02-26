# Philo Ventures Market Simulator

A product-agnostic simulation agent that generates realistic buyer personas, conducts AI-powered customer interviews, and produces McKinsey-grade insights reports — all from a single YAML config file.

Built for the Philo Ventures portfolio. Designed to help founders validate assumptions, test product-market fit hypotheses, and explore new markets before investing time and money in real-world experiments.

---

## Quick Start

### 1. Install Dependencies

```bash
pip3 install openai pyyaml
```

### 2. Set Your API Key

```bash
export OPENAI_API_KEY="your-key-here"
```

### 3. Create a Config File

Copy the blank template and fill in your product details:

```bash
cp -r examples/blank my_simulation
# Edit my_simulation/config.yaml with your product details
```

### 4. Run the Simulation

```bash
python3 run.py my_simulation/config.yaml
```

The simulator will:
1. Auto-generate a world model for your target market (or use one you provide)
2. Generate 100 diverse buyer personas
3. Conduct 5-turn interviews with each persona
4. Analyze all interviews and produce a comprehensive report

Output is saved to the `output/` directory specified in your config.

---

## How It Works

### The Four-Layer Architecture

```
┌─────────────────────────────────────────────┐
│  YAML Config (product, market, questions)    │
└──────────────────┬──────────────────────────┘
                   │
         ┌─────────▼──────────┐
         │  Research Engine    │  Auto-generates world model
         │  (if no file given)│  for the target market
         └─────────┬──────────┘
                   │
         ┌─────────▼──────────┐
         │  Persona Engine    │  Generates N diverse buyer
         │                    │  personas across archetypes
         └─────────┬──────────┘
                   │
         ┌─────────▼──────────┐
         │  Interview Engine  │  5-turn conversational
         │                    │  interviews with each persona
         └─────────┬──────────┘
                   │
         ┌─────────▼──────────┐
         │  Analysis Engine   │  McKinsey-grade report with
         │                    │  quotes, data, recommendations
         └──────────────────────┘
```

### Buyer Archetypes

The simulator uses six default buyer archetypes (customizable in config):

| Archetype | Weight | Skepticism | Description |
|-----------|--------|------------|-------------|
| Overwhelmed Founder | 25% | 3-6 | Resource-constrained, wants to be told what to do |
| Data-Hungry Operator | 15% | 6-9 | Analytical, compares to their own data |
| Automation-First Buyer | 15% | 5-8 | Wants action, not dashboards |
| Competitive Evaluator | 15% | 6-9 | Comparing alternatives, negotiates |
| Strategic Enterprise | 10% | 7-10 | Evaluating a partner, not a product |
| Red Team Skeptic | 10% | 8-10 | Designed to say no — reveals real barriers |

### Anti-Sycophancy Calibration

A key challenge with LLM-based simulations is that personas tend to be too agreeable. The simulator addresses this through:

- **Disposition weighting**: Only ~10% of personas are "enthusiastic." ~40% are skeptical or resistant.
- **Skepticism scores**: Each persona has a 1-10 skepticism score that shapes their responses.
- **Red Team archetype**: 10% of the audience is explicitly designed to push back hard.
- **Interviewer training**: The interviewer agent stress-tests positive signals and doesn't lead the witness.
- **Sycophancy detection**: The analysis engine flags responses that seem artificially positive.

---

## Config Reference

### Product Section (Required)

```yaml
product:
  name: "Your Product"
  description: |
    What it does, who it's for, pricing, stage.
  target_market: |
    Industry, company size, buyer role, geography.
```

### Assumptions & Questions (At Least One Required)

```yaml
# Hypothesis validation (produces validated/invalidated verdicts)
assumptions:
  - "Mid-market HVAC companies would pay $300/month for predictive analytics"

# Open-ended exploration (produces thematic insights)
questions:
  - "How do you currently handle customer retention?"
```

### Settings (Optional — Defaults Shown)

```yaml
settings:
  persona_count: 100              # Number of simulated prospects
  interview_turns: 5              # Conversation turns per interview
  interaction_context: "warm_demo" # warm_demo | cold_outreach | blended
  llm_model: "gemini-2.5-flash"  # LLM model to use
  persona_concurrency: 5          # Parallel persona generation batches
  interview_concurrency: 10       # Parallel interviews
```

### Context Files (Optional — Improve Accuracy)

```yaml
context:
  world_model: "context/world_model.md"    # Market research, competitors, benchmarks
  transcripts: "context/transcripts.md"    # Real sales call transcripts
  customer_list: "context/customer_list.md" # Existing customer details
```

**Accuracy levels by context provided:**
- No context: C+ (directional, based on LLM knowledge)
- World model only: B- (grounded in market data)
- World model + customer list: B (calibrated against real buyers)
- World model + customer list + transcripts: B+ (calibrated against real conversations)

---

## Output Files

Each simulation run produces:

| File | Description |
|------|-------------|
| `report.md` | The full McKinsey-grade insights report |
| `transcripts.md` | All interview transcripts in readable format |
| `audience_summary.md` | Demographic breakdown of the simulated audience |
| `personas.json` | Raw persona data (for further analysis) |
| `interviews.json` | Raw interview data (for further analysis) |
| `insights.json` | Structured insight extractions |
| `run_metadata.json` | Config snapshot and run statistics |
| `generated_world_model.md` | Auto-generated world model (if no file provided) |

---

## Tips for Best Results

1. **Be specific in your target market definition.** "Service businesses" is too broad. "Subscription-based residential pest control companies with 1,000-10,000 customers" produces much better personas.

2. **Provide real context when you have it.** Even 3-5 sales call transcripts dramatically improve the realism of simulated interviews.

3. **Test one thing at a time.** Running 2 assumptions + 4 questions in one simulation dilutes the interview depth. Better to run focused simulations.

4. **Read the transcripts, not just the report.** The individual conversations often contain insights that the aggregate analysis misses.

5. **Use the report as a starting point, not a conclusion.** The simulation tells you where to look. Real customer interviews tell you what's true.

6. **Run the same simulation twice.** If the findings are consistent across runs, they're more likely to be real signal. If they diverge, the finding is probably noise.

---

## Customizing Archetypes

You can override the default archetypes in your config:

```yaml
archetypes:
  my_custom_archetype:
    name: "The Budget-Conscious CFO"
    description: "Evaluates everything through an ROI lens..."
    behaviors:
      - "Asks about payback period immediately"
    buying_triggers:
      - "Clear, quantified ROI within 90 days"
    common_objections:
      - "What's the payback period?"
    skepticism_range: [7, 9]
    typical_weight: 0.20
```

---

## Architecture

```
philo_simulator/
├── run.py                    # Main entry point (CLI)
├── config.py                 # Config loader and defaults
├── engines/
│   ├── llm_client.py         # LLM API wrapper with retry logic
│   ├── persona_engine.py     # Persona generation
│   ├── interview_engine.py   # Multi-turn interview conductor
│   ├── analysis_engine.py    # Insight extraction and report generation
│   └── research_engine.py    # Auto world model generation
├── examples/
│   ├── revhawk/              # RevHawk example (with context files)
│   │   ├── config.yaml
│   │   └── context/
│   └── blank/                # Blank template to copy
│       └── config.yaml
└── README.md
```

---

## License

Internal tool — Philo Ventures. Not for distribution.
