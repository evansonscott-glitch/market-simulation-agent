# Refinery Affiliate — World Model for Slack Agent Simulation

## 1. The Affiliate Marketing Industry

### Market Size & Growth
- Global affiliate marketing platform market: ~$22.6 billion in 2025, projected to reach $35.7 billion by 2033 (CAGR 5.9%) [Grand View Research]
- Affiliate marketing software specifically: growing at 12-15% CAGR through 2035 [LinkedIn/Business Research Company]
- The industry is mature but undergoing significant transformation due to AI adoption

### Key Affiliate Networks / Platforms
| Platform | Market Position | Pricing | Notes |
|----------|----------------|---------|-------|
| Impact.com | Leading partnership management platform | $30/mo (Starter) to $2,500+/mo (Pro/Enterprise) | Largest independent platform, 300K+ partners marketplace |
| CJ Affiliate (Commission Junction) | Legacy leader, owned by Publicis | Enterprise pricing | Strong with large advertisers |
| AWIN | Major global network | Varies by program | Strong in Europe, growing in US |
| Rakuten Advertising | Enterprise-focused | Enterprise pricing | Part of Rakuten Group |
| ShareASale | Mid-market, owned by AWIN | Lower entry point | Popular with SMBs |
| Partnerize | Enterprise partnership automation | Enterprise pricing | Strong in retail/travel |
| Everflow | Growing challenger | Performance-based | Strong automation features |

### Industry Challenges (Verified)
- **Fraud**: Impacts ~67% of affiliate managers [Affiverse Media]
- **Tracking inconsistencies**: Cross-device, cookie deprecation, attribution gaps
- **Time management**: Managing multiple affiliates is extremely time-consuming
- **Data overload**: Too much data, not enough actionable insights
- **Partner recruitment**: Finding and vetting quality affiliates is manual and slow
- **Budget justification**: 46% of marketers globally cite affiliate marketing budgets as a challenge [Fintel Connect]

## 2. The Affiliate Manager Persona

### Role Overview
- An affiliate manager manages an online affiliate program for an advertiser or merchant
- They recruit new affiliates, manage onboarding, ensure audience alignment, liaise with existing affiliates, address concerns, resolve issues
- They create and implement strategy, make recommendations about best practices

### Daily Tasks (Verified from Multiple Sources)
1. **Morning**: Review pending applications, check emails, review performance dashboards
2. **Mid-day**: Recruiting new affiliates, creating/uploading banners, compliance review
3. **Afternoon**: Analyzing campaign data, optimizing placements, relationship management
4. **Ongoing**: Payment processing, fraud monitoring, reporting to management

### Time Allocation
- Each affiliate manager typically spends 1-2 hours per client per day [Matt McWilliams]
- Significant time spent on manual data analysis and reporting
- Recruitment and relationship management consume large portions of the day

### Salary Data
- Average affiliate manager salary: $81,198 - $135,584/year in the US [Glassdoor, Comparably]
- Average hourly: ~$47.56 [ZipRecruiter]
- Range: $35,884 to $365,965 depending on seniority and company size

### Key Pain Points (Verified)
1. **Too many missed opportunities**: Can't review all data manually
2. **Manual, time-consuming processes**: Partner vetting, performance tracking, fraud detection
3. **Inconsistent tracking**: Inaccurate data makes optimization difficult
4. **Affiliate fraud**: Fake clicks, fraudulent conversions
5. **Misaligned KPIs**: Difficulty defining and tracking the right metrics
6. **Complex onboarding**: Identifying suitable affiliates and getting them productive
7. **Payment management**: Ensuring timely, accurate payments
8. **Reporting burden**: Delivering reports to advertisers and senior management

## 3. The Buyer Hierarchy

### Champion (Day-to-Day User)
- **Title**: Affiliate Manager, Affiliate Marketing Manager, Partnership Manager
- **Concerns**: Time savings, better insights, easier workflow, competitive advantage
- **Decision power**: Can recommend tools, influence budget, but rarely has final say on $300-$1K/month spend

### Budget Holder (Decision Maker)
- **Title**: VP of Marketing, Head of Affiliate Marketing, Director of Partnerships, CMO
- **Concerns**: ROI, revenue growth, team efficiency, competitive positioning, data security
- **Decision power**: Approves budget, signs contracts, evaluates ROI

### Typical Team Sizes
- Small programs: 1 affiliate manager handling 1-3 programs
- Mid-market: 2-5 affiliate managers with a director/VP overseeing
- Enterprise: 5-15+ affiliate managers, dedicated analytics, VP-level leadership
- Agencies: Teams of affiliate managers each handling multiple client programs

## 4. Refinery Affiliate — Current Product

### What It Does Today
- AI-powered affiliate partner discovery and performance insights
- Consolidates affiliate program data into one dashboard
- Surfaces 150+ actionable insights from affiliate program data
- Features: Partnership Discovery, AI Tools, Insights & Actions, Manager Attribution & Reporting, Placement Tracking, Fraud Protection

### Current Positioning
- "AI-Powered Affiliate Partner Discovery + Performance Insights"
- "Refinery AI turns complex data into clear actions, helping affiliate managers overcome revenue plateaus, inefficient spending, and program vulnerabilities"
- Targets both advertisers (brands) and agencies

### Current Pricing
- $300 - $1,000/month depending on number of programs managed

### Current Challenge
- **Adoption is the problem, not pricing**: People are hard to get in and using it
- The product requires users to log into a separate dashboard — another tool in an already crowded stack
- Affiliate managers are busy and resistant to adding new platforms to their workflow

### Integrations
- Impact.com (primary ecosystem)
- Also works with clients using AWIN, CJ, Rakuten

## 5. The Proposed Pivot: Slack-Native AI Agent

### Concept
Instead of a standalone SaaS dashboard, Refinery becomes an AI agent that lives in the affiliate manager's Slack workspace. It proactively reviews affiliate network data (Impact.com, CJ, AWIN, Rakuten) and surfaces insights, alerts, and recommendations directly in Slack — without the user having to log into anything.

### Key Capabilities (Proposed)
1. **Dormant Affiliate Alerts**: "Hey, Affiliate X went dark but represented $45K in revenue last month — you should check in"
2. **Trending Partner Signals**: "Affiliate Y's ROAS is up 35% this month — see if they can do more volume"
3. **Fraud Detection**: "Suspicious click patterns detected from Affiliate Z — 8K excessive clicks flagged"
4. **New Partner Recommendations**: "Based on your program profile, these 5 affiliates in your network could be a good fit"
5. **Revenue Leakage Alerts**: "MoM revenue decreased $87.7K — here are the top 3 contributing factors"
6. **ROAS Optimization**: "Your ROAS efficiency dropped 11% — here's where the inefficiency is"
7. **Proactive Weekly Digests**: Summary of program health, opportunities, and action items

### Why This Might Work
- **Slack adoption in enterprise**: Native Slack tools achieve 90%+ adoption vs. 70% for third-party tools [Pylon]
- **Zero friction onboarding**: No new login, no new dashboard to learn
- **Proactive vs. reactive**: Insights come to you instead of you going to find them
- **Slack is investing heavily in AI agents**: Slack's own Slackbot is becoming an AI agent, Agentforce integration, MCP server support — the ecosystem is ready
- **Trend toward "ambient intelligence"**: Users prefer tools that work in the background and surface insights when relevant

### Potential Concerns
- **Data security**: Connecting affiliate network data to a Slack bot raises security questions
- **Trust**: Will managers trust AI recommendations about their affiliate relationships?
- **Noise vs. signal**: Too many alerts could become annoying; too few and it's not valuable
- **Pricing justification**: Is a Slack bot worth $300-$1K/month? Or does the form factor suggest it should be cheaper?
- **Enterprise IT approval**: Getting a third-party bot approved in corporate Slack workspaces
- **Depth of analysis**: Can a Slack message convey the same depth as a full dashboard?

## 6. Competitive Landscape for AI in Affiliate Management

### Direct Competitors
- **Everflow**: Automation features for tracking, reporting, payment, fraud detection. Traditional SaaS dashboard.
- **Levanta/Grovia**: AI-powered affiliate discovery, focused on Amazon marketplace. Traditional SaaS.
- **PartnerCentric**: Agency + technology hybrid, uses proprietary tech for optimization.

### Adjacent Competitors
- **Impact.com's own AI features**: The platforms themselves are adding AI capabilities
- **General BI tools**: Looker, Tableau, etc. used by larger teams for affiliate analytics
- **Dataslayer AI Insights**: AI-powered marketing analytics across channels

### Key Insight
No one is currently offering a Slack-native AI agent specifically for affiliate program management. This would be a genuinely novel form factor in the space. The closest analogies are:
- Slack-based customer support tools (Plain, Pylon)
- Slack-based project management (which achieve 90%+ adoption)
- Proactive AI agents in Slack (Salesforce Agentforce, custom bots)

## 7. Market Sizing for the Slack Agent

### Addressable Market
- Estimated 10,000-30,000 companies running affiliate programs in the US with dedicated affiliate managers
- Of those, roughly 40-60% use Impact.com, CJ, AWIN, or Rakuten as their primary platform
- At $300-$1K/month, the addressable market for this tool is roughly $50M-$300M annually
- Realistic penetration at 1-5% in first 3 years: $500K - $15M ARR potential
