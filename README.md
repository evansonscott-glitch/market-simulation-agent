# Market Simulator

An AI-powered thinking partner that helps founders and investors validate product assumptions through simulated customer interviews. It coaches you through identifying risks, mapping assumptions, and designing the right interview process — then runs the simulation and delivers McKinsey-grade insights.

This repo contains two things:
1. **The Simulation Engine** — A standalone Python pipeline that generates personas, conducts multi-turn interviews, runs bias audits, and produces McKinsey-grade reports with statistical validation.
2. **The Claude Code Skill** — A reusable methodology for running iterative, self-improving simulations inside [Claude Code](https://claude.ai/code), including a 7-dimension scoring engine and a Karpathy-style "autoresearch" loop.

**Four interfaces, one engine:**

| Interface | Best For | How |
|-----------|----------|-----|
| **Claude Code** | Guided experience, iteration, coaching | Open repo in Claude Code → `/user-simulation` |
| **Slack Bot** | Team collaboration, async simulations | `/simulate` in Slack |
| **CLI** | Quick runs, scripting, power users | `python cli/interactive.py` |
| **Web App** | Visual interface, demos, sharing | `python web/server.py` |

---

## How It Works

### The Conversational Flow

Instead of requiring a config file upfront, the simulator acts as a **thinking partner** that guides you through five stages:

```
Stage 1: The Idea Dump        →  "Tell me about your product."
Stage 2: Value Proposition     →  "What's the single biggest benefit?"
Stage 3: Customer Segments     →  "Are all your customers the same?"
Stage 4: Assumptions & Risks   →  "What has to be true for this to work?"
Stage 5: Simulation Plan       →  "Here's what I'll test. Ready?"
```

The agent uses the Socratic method — it doesn't just accept "people will love it." It pushes back: *"OK, but for the business to work, what has to be true?"*

Once you confirm the plan, it:
1. **Researches** your market automatically (web research + LLM knowledge)
2. **Generates** realistic buyer personas across your target segments
3. **Conducts** multi-turn interviews with each persona
4. **Analyzes** all interviews and produces a comprehensive report

### The Four-Layer Engine

```
┌─────────────────────────────────────────────┐
│  Conversational Config (from any interface)  │
└──────────────────┬──────────────────────────┘
                   │
         ┌─────────▼──────────┐
         │  Research Engine    │  Auto-generates world model
         └─────────┬──────────┘
                   │
         ┌─────────▼──────────┐
         │  Persona Engine    │  Generates diverse buyer
         │                    │  personas across archetypes
         └─────────┬──────────┘
                   │
         ┌─────────▼──────────┐
         │  Interview Engine  │  Multi-turn conversational
         │                    │  interviews with each persona
         └─────────┬──────────┘
                   │
         ┌─────────▼──────────┐
         │  Analysis Engine   │  McKinsey-grade report with
         │                    │  quotes, data, recommendations
         └──────────────────────┘
```

---

## Quick Start

### Option 1: Claude Code (Recommended)

Open this repo in [Claude Code](https://claude.ai/code) and say:

> "I want to run a market simulation for my product"

Claude will trigger the `/user-simulation` skill and walk you through:
1. Describing your product and target market
2. Identifying assumptions to test
3. Providing context (transcripts, customer data, market research)
4. Running the simulation and scoring results
5. Iterating to improve fidelity

The skill orchestrates all the Python engines in this repo — persona generation, interviews, bias auditing, statistical validation — so you get production-grade output with a conversational experience.

**Requirements:** An OpenAI-compatible API key set in your environment (`OPENAI_API_KEY`). Default model is `gemini-2.5-flash`.

### Option 2: Interactive CLI

```bash
# Install dependencies
pip3 install openai pyyaml pydantic

# Set your API key
export OPENAI_API_KEY="your-key-here"

# Start the interactive session
python cli/interactive.py
```

The agent will guide you through the entire process conversationally.

### Option 3: Slack Bot (Recommended for Teams)

```bash
# Install dependencies
pip3 install openai pyyaml pydantic slack-bolt python-dotenv

# Copy and fill in your environment variables
cp .env.example .env
# Edit .env with your Slack and OpenAI credentials

# Start the bot
python slack_bot/app.py
```

See [SLACK_SETUP.md](SLACK_SETUP.md) for step-by-step Slack app creation instructions.

### Option 4: Web App

```bash
# Install dependencies
pip3 install openai pyyaml pydantic fastapi uvicorn

# Start the web server
python web/server.py
```

Open `http://localhost:8080` in your browser.

### Option 5: Config File (Power Users)

If you prefer to skip the conversation and run from a YAML config:

```bash
# Copy the blank template
cp -r examples/blank my_simulation

# Edit my_simulation/config.yaml with your product details
python run.py my_simulation/config.yaml
```

### Docker Deployment

```bash
# Build and run with Docker Compose
cp .env.example .env
# Edit .env with your credentials
docker compose up -d
```

---

## Feeding It Real Data

The simulator gets dramatically better with real-world context. You can provide:

| Context Type | How to Provide | Impact |
|-------------|----------------|--------|
| **Sales call transcripts** | Share Attio links, paste transcripts, or upload files | Personas use real customer language and objections |
| **Customer list** | Describe your current customers | Personas calibrated against real buyer profiles |
| **Market research** | Share articles, competitor info, industry data | World model grounded in actual market dynamics |

**Accuracy levels by context provided:**
- No context: C+ (directional, based on LLM knowledge)
- World model only: B- (grounded in market data)
- World model + customer list: B (calibrated against real buyers)
- World model + customer list + transcripts: B+ (calibrated against real conversations)

---

## Anti-Sycophancy Calibration

A key challenge with LLM-based simulations is that personas tend to be too agreeable. The simulator addresses this through:

- **Disposition weighting**: Only ~10% of personas are "enthusiastic." ~40% are skeptical or resistant.
- **Skepticism scores**: Each persona has a 1-10 skepticism score that shapes their responses.
- **Red Team archetype**: 10% of the audience is explicitly designed to push back hard.
- **Interviewer training**: The interviewer agent stress-tests positive signals and doesn't lead the witness.
- **Sycophancy detection**: The analysis engine flags responses that seem artificially positive.

---

## Production Hardening (v2)

- **Structured logging** — Proper Python logging with level control, sensitive data redaction, file + console output
- **Config validation** — Pydantic models with clear, actionable error messages
- **Robust JSON parsing** — 5-strategy fallback pipeline for LLM response parsing
- **Error handling** — Retry logic with exponential backoff and jitter, graceful degradation
- **Token-aware rate limiting** — Respects API RPM/TPM limits with adaptive backoff
- **Crash recovery** — Checkpoint system saves state after each interview; resume with `--resume`
- **Memory management** — Streams interview results to disk incrementally for large simulations
- **API key protection** — Sensitive data filter automatically redacts keys/tokens from all log output

---

## Output Files

Each simulation run produces:

| File | Description |
|------|-------------|
| `report.md` | Strategic report with bias audit and statistical appendix |
| `transcripts.md` | All interview transcripts in readable format |
| `audience_summary.md` | Demographic breakdown of the simulated audience |
| `personas.json` | Full persona definitions with metadata |
| `interviews.json` | Raw interview data |
| `insights.json` | Structured insight extractions |
| `quantitative_summary.json` | Numerical scores and metrics |
| `bias_audit.json` | Disposition adherence and sycophancy detection results |
| `context_quality.json` | Context quality grade (A-F) and details |
| `scoring_report.md` | Per-dimension scoring breakdown (if scoring engine used) |
| `scoring_results.json` | Raw scoring data (if scoring engine used) |
| `run_metadata.json` | Timestamp, config snapshot, quality grades |
| `simulation.log` | Full structured log file |

---

## Claude Code Skill: Iterative Simulation Loop

The `skill/` directory contains a Claude Code skill that wraps the simulation engine in an iterative, self-improving workflow inspired by Andrej Karpathy's "autoresearch" concept.

### The Loop

```
Define World Model → Define Scoring Function → Run Simulation → Score Results → Revise & Refine → Commit & Iterate
                                                      ↑                                              |
                                                      └──────────────────────────────────────────────┘
```

### Scoring Engine (7 Code-Based Dimensions)

| Dimension | What It Measures | Score |
|---|---|---|
| Objection Bypass Rate | % of objections where agent response led to positive next turn | 0.0-1.0 |
| Attribute Consistency | 1.0 minus (contradictions / user turns) | 0.0-1.0 |
| Turns to Resolution | Normalized score based on turn count (fewer = better) | 0.0-1.0 |
| Trust Signal Hit Rate | % of trust objections followed by a trust signal within 2 turns | 0.0-1.0 |
| Cross-Sell Success Rate | % of cross-sell attempts getting positive reaction | 0.0-1.0 |
| Conversion | Did the conversation end in success? | 0.0 or 1.0 |
| Sentiment Velocity | Change in sentiment from first half to second half | 0.0-1.0 |

See [`skill/references/scoring_rubric.md`](skill/references/scoring_rubric.md) for the qualitative calibration rubric used for manual spot-checks.

### Using the Skill in Claude Code

1. Open this repo in Claude Code
2. Say "I want to run a market simulation" (or anything related to testing product assumptions)
3. Claude triggers the `/user-simulation` skill and walks you through the 6-step workflow
4. Each step uses the Python engines in this repo — no manual CLI commands needed

---

## Architecture

```
market-simulation-agent/
├── CLAUDE.md                           # Claude Code context and instructions
├── run.py                              # Main pipeline runner (single entry point)
├── config.py                           # YAML config loading + Pydantic validation
├── core/                               # Shared engine (interface-agnostic)
│   ├── conversation_engine.py          # 5-stage Socratic coaching flow
│   └── simulation_bridge.py            # Converts conversation → simulation config
├── engines/                            # Simulation pipeline
│   ├── persona_engine.py               # Stratified persona generation + anti-sycophancy
│   ├── interview_engine.py             # Async multi-turn interviews + checkpointing
│   ├── analysis_engine.py              # Insight extraction + McKinsey-grade reports
│   ├── scoring_engine.py               # 7-dimension code-based conversation scoring
│   ├── research_engine.py              # Auto world model generation
│   ├── market_census.py                # Statistically valid sample frame generator
│   ├── focus_group.py                  # Agent-to-agent focus group discussions
│   ├── temporal_sequence.py            # Multi-touch sales sequence simulation
│   ├── post_sim_chat.py                # Follow-up chat with personas post-simulation
│   ├── context_quality.py              # A-F context quality grading
│   ├── statistical_validation.py       # Confidence intervals, sample size, significance
│   ├── bias_detection.py               # Disposition adherence + sycophancy detection
│   ├── experiment_formats.py           # Format-specific prompts/metrics/caveats
│   ├── graph_memory.py                 # Lightweight knowledge graph for grounding
│   ├── llm_client.py                   # LLM wrapper with retry + rate limiting
│   ├── json_parser.py                  # Multi-strategy robust JSON parser
│   ├── checkpoint.py                   # Crash recovery via atomic writes
│   └── logging_config.py              # Structured logging + sensitive data filter
├── skill/                              # Claude Code Skill (iterative simulation loop)
│   ├── SKILL.md                        # Skill definition (6-step workflow)
│   └── references/
│       └── scoring_rubric.md           # Qualitative rubric for manual calibration
├── slack_bot/                          # Slack interface
│   └── app.py                          # Socket Mode bot with slash commands
├── cli/                                # CLI interface
│   └── interactive.py                  # Terminal-based conversational flow
├── web/                                # Web interface
│   ├── server.py                       # FastAPI + WebSocket backend
│   └── static/index.html               # Chat-style frontend
├── examples/                           # Example configs
│   ├── blank/config.yaml               # Blank template
│   ├── revhawk/                        # RevHawk example
│   └── refinery/                       # Refinery Affiliate example
├── REVIEW.md                           # Full review with 27 identified gaps
├── Dockerfile                          # Container deployment
├── docker-compose.yml                  # One-command deployment
├── requirements.txt                    # Python dependencies
└── SLACK_SETUP.md                      # Slack app creation guide
```

---

## Requirements

- Python 3.11+
- `openai` — LLM API client
- `pyyaml` — Config file parsing
- `pydantic` — Config validation
- `slack-bolt` — Slack bot (optional, for Slack interface)
- `fastapi` + `uvicorn` — Web server (optional, for web interface)

---

## Tips for Best Results

1. **Be specific in your target market definition.** "Service businesses" is too broad. "Subscription-based residential pest control companies with 1,000-10,000 customers" produces much better personas.

2. **Provide real context when you have it.** Even 3-5 sales call transcripts dramatically improve the realism of simulated interviews.

3. **Test one thing at a time.** Running 2 assumptions + 4 questions in one simulation dilutes the interview depth. Better to run focused simulations.

4. **Read the transcripts, not just the report.** The individual conversations often contain insights that the aggregate analysis misses.

5. **Use the report as a starting point, not a conclusion.** The simulation tells you where to look. Real customer interviews tell you what's true.

6. **Run the same simulation twice.** If the findings are consistent across runs, they're more likely to be real signal. If they diverge, the finding is probably noise.
