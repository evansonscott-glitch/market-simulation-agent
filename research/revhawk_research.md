# RevHawk Product Research

## Core Product
- AI-Powered Customer Retention for subscription-based home service businesses
- Currently focused on Pest Control industry
- Tagline: "Retention Pays. Acquisition Costs."

## Three Products:
1. **RevHawk Insights** - Executive level retention analysis & benchmarking, enabling strategic decisions
2. **RevHawk Actions** - AI-driven customer health scores, recommended next steps, and automated retention campaigns
3. **RevHawk Retention Manager** - All-in-one service saves tracking and analysis system built for customer retention teams

## How It Works:
1. Connect Your Data - Plug in your CRM (PestRoutes and others). Sync customer data.
2. AI Predicts Churn - AI analyzes patterns and flags at-risk customers before they cancel.
3. Step 3 - (likely: Take Action / Save Customers)

## Pain Points Addressed:
- Silent Churn: Customers cancel quietly with no warning
- No Time to Act: By the time you manually review accounts, cancellation already sent
- Expensive Blindspots: Acquiring new customers costs 5-7x more than retention

## Trusted By:
- Glide, Evo Pest Control, Frontline, Ruva, 4EverGone, RIDD

## Testimonial:
- Ethan Brown, President of Customer Care: "RevHawk is enabling all the things I've known we need to do for retention with data, but don't have the time, skillsets, or scale to do ourselves."

## Key Assumptions to Test (from Scott):
1. Other service business categories (beyond pest control) have owners/operators who would also want this
2. If RevHawk built a proactive engagement layer that actually did outreach (instead of just alerting), customers would pay even more

## Attio Call Intelligence Findings

### Features:
- **Native call recording** built into Attio (Pro and Enterprise plans)
- **Real-time transcription** with speaker labels and timestamps
- **Transcripts in 100+ languages**
- **AI-powered insight templates** - customizable prompts that extract structured insights from transcripts (e.g., SPICED, MEDDIC frameworks)
- **Automatic linking** - recordings linked to relevant CRM records (companies, people, deals)
- **Focus Mode** - zoom in on key decision makers
- **Buying signal detection** - AI picks up signals, blockers, requests during calls

### API Access:
- **Webhook**: `call-recording.created` event fires when a call recording finishes and media upload is complete
- Contains event_type, id, and actor data
- The REST API has endpoints for core objects, standard objects, and webhook events
- Call recordings are linked to records (companies, people)
- There's community demand for an Activity/Interactions API for managing calls programmatically

### Key Insight for Our Build:
- Attio transcribes calls automatically with speaker labels
- We can likely access transcripts through the API or export them
- Insight templates could be customized to extract exactly the data we need for persona building
- The webhook system means we could potentially auto-ingest new call recordings as they happen
