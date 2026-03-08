# Market Simulator

An AI-powered thinking partner that helps founders and investors validate product assumptions through simulated customer interviews. It coaches you through identifying risks, mapping assumptions, and designing the right interview process — then runs the simulation and delivers McKinsey-grade insights.

This repo contains two things:
1. **The Simulation Engine** — A standalone Python tool that generates personas, conducts multi-turn interviews, and produces McKinsey-grade reports.
2. **The Manus Skill** — A reusable methodology for running iterative, self-improving simulations inside [Manus](https://manus.im), including a 7-dimension scoring rubric and a Karpathy-style "autoresearch" loop.

**Three interfaces, one engine:**

| Interface | Best For | Command |
|-----------|----------|---------|
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

### Option 1: Interactive CLI (Fastest)

```bash
# Install dependencies
pip3 install openai pyyaml pydantic

# Set your API key
export OPENAI_API_KEY="your-key-here"

# Start the interactive session
python cli/interactive.py
```

The agent will guide you through the entire process conversationally.

### Option 2: Slack Bot (Recommended for Teams)

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

### Option 3: Web App

```bash
# Install dependencies
pip3 install openai pyyaml pydantic fastapi uvicorn

# Start the web server
python web/server.py
```

Open `http://localhost:8080` in your browser.

### Option 4: Config File (Power Users)

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
| `report.md` | The full McKinsey-grade insights report |
| `transcripts.md` | All interview transcripts in readable format |
| `audience_summary.md` | Demographic breakdown of the simulated audience |
| `insights.json` | Structured insight extractions |
| `quantitative_summary.json` | Numerical scores and metrics |
| `config.yaml` | Snapshot of the simulation config |
| `simulation.log` | Full structured log file |

---

## Manus Skill: Iterative Simulation Loop

The `skill/` directory contains a [Manus Skill](https://manus.im) that wraps the simulation engine in an iterative, self-improving workflow inspired by Andrej Karpathy's "autoresearch" concept.

### The Loop

```
Define World Model → Define Scoring Function → Run Simulation → Score Results → Revise & Refine → Commit & Iterate
                                                      ↑                                              |
                                                      └──────────────────────────────────────────────┘
```

### Scoring Rubric (7 Dimensions)

| Dimension | What It Measures | Scale |
|---|---|---|
| Objection Handling Fidelity | Does the agent deploy the proven response for each objection type? | 1-5 |
| Persona Consistency | Does the simulated user behave like their defined archetype? | 1-5 |
| Conversation Efficiency | How many turns to reach a clear outcome? | 1-5 |
| Trust Signal Deployment | Does the agent weave in trust signals at the right moments? | 1-5 |
| Cross-Sell Opportunity ID | Does the agent recognize and act on natural cross-sell moments? | 0-1 |
| Conversion Rate (by Trigger) | What % of simulations end in a successful outcome? | 0-100% |
| Emotional Arc Realism | Does the conversation follow a believable emotional trajectory? | 1-5 |

See [`skill/references/scoring_rubric.md`](skill/references/scoring_rubric.md) for the full rubric.

### Using the Skill in Manus

1. Add the skill to your Manus workspace (upload `skill/SKILL.md`)
2. In any conversation, mention that you want to simulate user interactions, test assumptions, or build a knowledge base
3. The skill triggers and walks you through the 6-step workflow conversationally

---

## Architecture

```
market-simulation-agent/
├── core/                               # Shared engine (interface-agnostic)
│   ├── conversation_engine.py          # 5-stage coaching flow + LLM orchestration
│   └── simulation_bridge.py            # Converts conversation → simulation config
├── engines/                            # Simulation pipeline
│   ├── logging_config.py               # Structured logging + sensitive data filter
│   ├── llm_client.py                   # LLM wrapper with retry, rate limiting
│   ├── json_parser.py                  # Multi-strategy JSON parser
│   ├── checkpoint.py                   # State persistence for crash recovery
│   ├── persona_engine.py               # Persona generation with anti-sycophancy
│   ├── interview_engine.py             # Multi-turn interviews with checkpointing
│   ├── analysis_engine.py              # Insight extraction + report generation
│   └── research_engine.py              # Auto world model generation
├── slack_bot/                          # Slack interface
│   └── app.py                          # Socket Mode bot with slash commands
├── cli/                                # CLI interface
│   └── interactive.py                  # Terminal-based conversational flow
├── web/                                # Web interface
│   ├── server.py                       # FastAPI + WebSocket backend
│   └── static/index.html               # Chat-style frontend
├── run.py                              # Config-file runner (power users)
├── config.py                           # Config loading + Pydantic validation
├── examples/                           # Example configs
│   ├── blank/config.yaml               # Blank template
│   ├── revhawk/                        # RevHawk example
│   ├── refinery/                       # Refinery Affiliate example
│   └── checkk/                         # Checkk.ai example
├── Dockerfile                          # Container deployment
├── docker-compose.yml                  # One-command deployment
├── requirements.txt                    # Python dependencies
├── SLACK_SETUP.md                      # Slack app creation guide
├── skill/                              # Manus Skill (iterative simulation loop)
│   ├── SKILL.md                        # Skill definition (6-step workflow)
│   └── references/
│       └── scoring_rubric.md           # 7-dimension scoring function
└── README.md
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
