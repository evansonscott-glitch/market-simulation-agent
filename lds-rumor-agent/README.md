# LDS Church Rumor Intelligence Agent

A weekly automated agent that aggregates speculative claims about The Church of Jesus Christ of Latter-day Saints from public sources, scores them using a Bayesian model trained on historical rumor-to-outcome data, and delivers a ranked digest via email.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
pip install beautifulsoup4 praw playwright
playwright install chromium

# 2. Configure
cp config/config.example.yaml config/config.yaml
# Edit config.yaml with your API keys, or set env vars:
export ANTHROPIC_API_KEY="..."
export REDDIT_CLIENT_ID="..."
export REDDIT_CLIENT_SECRET="..."
export GMAIL_ADDRESS="..."
export GMAIL_APP_PASSWORD="..."
export DIGEST_RECIPIENT="..."

# 3. Run Phase 1 training (one-time)
python3 scripts/initial_train.py

# 4. Run weekly pipeline (or set up cron)
python3 agent/weekly_run.py

# 5. Set up cron for weekly delivery
# 0 8 * * 6 cd /path/to/lds-rumor-agent && python3 agent/weekly_run.py >> /var/log/lds-rumor-agent.log 2>&1
```

## Architecture

```
Phase 1 (Training):
  Newsroom Scraper → Ground Truth → Claude Matcher → Labeled Dataset → Bayesian Priors

Phase 2 (Weekly):
  Reddit Scraper → Claude Classifier → Clusterer → Scorer → Resolver → Digest Email
```

## Components

| Component | File | Purpose |
|-----------|------|---------|
| Data Models | `models.py` | Pydantic schemas for all data |
| Newsroom Scraper | `scrapers/newsroom_scraper.py` | Official announcement timeline |
| Reddit Scraper | `scrapers/reddit_scraper.py` | Speculation from LDS subreddits |
| Classifier | `rumor_engine/classifier.py` | Claude-powered claim extraction |
| Clusterer | `rumor_engine/clusterer.py` | Group corroborating rumors |
| Matcher | `rumor_engine/matcher.py` | Match rumors to outcomes |
| Scorer | `rumor_engine/scorer.py` | Bayesian probability engine |
| Resolver | `rumor_engine/resolver.py` | Check predictions against news |
| Weekly Pipeline | `agent/weekly_run.py` | Main cron orchestrator |
| Digest Generator | `agent/digest_generator.py` | HTML email via Gmail SMTP |
| Self-Audit | `agent/self_audit.py` | Monthly calibration checks |

## Tests

```bash
cd lds-rumor-agent
python3 -m pytest tests/ -v
```

## Scoring

Rumors are scored using naive Bayes across 6 feature dimensions:
- **Category** (temple, leadership, policy, etc.)
- **Specificity** (exact location vs vague)
- **Source type** (named insider vs speculation)
- **Platform** (which subreddit)
- **Corroboration** (independent source count)
- **Author track record** (past prediction accuracy)

Confidence tiers: **high** (>0.65), **medium** (0.35-0.65), **low** (0.15-0.35), **noise** (<0.15)
