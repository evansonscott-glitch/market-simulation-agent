# RevHawk Buyer Fingerprint Analysis

## The Customer Base at a Glance

RevHawk has 11 paying customers with MRR ranging from $150 to $350 (average ~$245/month). The research reveals a remarkably coherent buyer profile with some important variations that will directly inform how we build the simulation agent's persona engine.

## Company Profile Patterns

### Industry Breakdown

| Category | Count | Companies |
|----------|-------|-----------|
| Pest Control | 10 | Evo, Recon, Ruva, Frontline, RIDD, 4-Evergone, Admiral, TruBug, BugBros, SPRK |
| Cleaning Services | 1 | Glide Cleaners |

The portfolio is overwhelmingly pest control (91%), with Glide Cleaners as the lone cross-vertical proof point. This is important for Assumption 1 — the expansion thesis has exactly one data point so far.

### Company Size Distribution

| Size Tier | Employee Range | Count | Companies | MRR Range |
|-----------|---------------|-------|-----------|-----------|
| Small | 1-10 | 3 | 4-Evergone, TruBug, SPRK | $150-$300 |
| Mid-size | 11-50 | 4 | Ruva, Glide, Admiral, BugBros | $150-$350 |
| Growth-stage | 51-200 | 2 | Evo, Frontline | $150-$300 |
| Scaled | 90+ with 13 branches | 1 | RIDD | $350 |
| Unknown | — | 1 | Recon (~19-25) | $350 |

RevHawk sells across a wide size spectrum. There's no single "sweet spot" — they're winning deals from 2-person shops to companies with $25M in revenue. This suggests the value prop resonates at multiple scales, but the *reasons* for buying likely differ by size tier.

### Geographic Distribution

| Region | Companies |
|--------|-----------|
| Utah | Evo (Orem), RIDD (Lehi), Glide (Provo) |
| East Coast / Mid-Atlantic | Frontline (MD), SPRK (VA) |
| Midwest | Recon (NE), BugBros (OK) |
| South / Southeast | 4-Evergone (FL), RIDD (multi-state) |
| West Coast | Admiral (CA), TruBug (CA) |
| Northeast | Ruva (CT) |

Good geographic diversity. No single region dominates, which suggests the problem (churn in subscription pest control) is universal, not regional.

### Company Age

| Founded | Count | Companies |
|---------|-------|-----------|
| Pre-2010 (established) | 2 | Admiral (1947!), 4-Evergone (2009) |
| 2010-2019 | 3 | BugBros (2015), Glide (2018), SPRK (2018) |
| 2020-2024 (newer) | 5 | Recon (2020), RIDD (2020), TruBug (2022), Ruva (~2023), Evo (2024) |
| Unknown | 1 | Frontline (2008 per research) |

Interesting skew toward newer companies. 5 of 11 were founded 2020 or later. These are companies in growth mode that are acquiring customers fast and starting to feel the pain of churn as they scale. This is a critical persona attribute — the buyer is likely a founder/operator who's past the initial survival phase and now dealing with retention for the first time.

### Customer Segment Focus

| Focus | Count | Companies |
|-------|-------|-----------|
| Residential only | 5 | Evo, Ruva, RIDD, TruBug, Frontline |
| Residential + Commercial | 5 | Recon, 4-Evergone, Admiral, BugBros, SPRK |
| Residential + Commercial | 1 | Glide |

Roughly even split. No strong signal that residential-only or mixed companies are more likely to buy.

### Market Positioning

| Positioning | Count | Companies |
|-------------|-------|-----------|
| Premium | 5 | Ruva, Frontline, RIDD, TruBug, BugBros |
| Mid-market | 3 | Evo, Admiral, SPRK |
| Mid-to-Premium | 2 | Recon, 4-Evergone |
| Premium | 1 | Glide |

Strong skew toward premium positioning. Companies that charge more for their services are more likely to buy RevHawk. This makes intuitive sense — premium operators have higher customer lifetime values, so each churned customer costs them more. The ROI case for churn prediction is stronger when your average customer is worth more.

### CRM/Technology

| CRM | Count | Companies |
|-----|-------|-----------|
| FieldRoutes | 3 | Evo, RIDD, Admiral |
| Unknown/Not identified | 8 | All others |

Only 3 confirmed FieldRoutes users. The rest likely use PestRoutes, Briostack, or other industry CRMs but it wasn't publicly identifiable. This is an important data point for Cameron — the CRM integration requirement is a real constraint on who can onboard.

### Buyer Role Pattern

| Role | Companies |
|------|-----------|
| Founder/Owner | Evo (Ian Hodge), Ruva (Scott Sandberg/Trevor Sharp), TruBug (JD Cruz), BugBros (Aaron/Jason Thomas), SPRK (Patrick Moyer), RIDD (Jason Wilde), 4-Evergone (David Bendit) |
| President/VP | Recon (Benjamin Sommers), Frontline (Darren Kirkham), Admiral (Trevor Jones) |
| CEO | Glide (Nathan Miller) |

The buyer is almost always the **founder or owner**. This is not a tool being purchased by a retention team or a marketing department — it's being bought by the person who built the company and feels the pain of churn personally. This is a critical insight for persona generation.

## The Buyer Fingerprint

Based on this analysis, the "typical" RevHawk buyer looks like this:

**The Archetype:** A founder/owner of a subscription-based pest control company, 3-7 years old, in growth mode (scaling from local to regional), positioned as premium or mid-to-premium, serving primarily residential customers, with 10-100+ employees. They've built the business through hustle and are now hitting the wall where manual retention efforts can't keep up with growth. They feel churn personally because every lost customer represents revenue they fought hard to acquire.

**Why they buy:** The 5-7x acquisition cost vs. retention cost is real to them — they've lived it. They know they should be doing more about retention but don't have the time, the data skills, or the team to do it systematically. RevHawk gives them visibility they've never had before.

**What they pay:** $150-$350/month MRR. The higher-paying customers ($300-$350) tend to be either larger operations (RIDD, Frontline, Admiral) or companies that place high value on data-driven operations (Recon).

**Key variations that matter for simulation:**
1. Company size creates different buying motivations (small = survival, mid = growth, large = optimization)
2. Premium vs. mid-market positioning affects willingness to pay and ROI sensitivity
3. Newer companies may be more tech-forward but less established in their retention processes
4. Multi-location companies have more complex churn patterns and higher stakes

## Implications for the Simulation Agent

### For Assumption 1 (Cross-vertical expansion):
The persona engine should generate operators in lawn care, HVAC, cleaning, plumbing, and pool service who match the same archetype: founder-led, subscription-based, growth-stage, premium-positioned. The key variables to test are whether these verticals have (a) the same data infrastructure (CRM with customer history), (b) the same churn pain intensity, and (c) the same willingness to pay $150-$350/month for predictive analytics.

### For Assumption 2 (Proactive engagement layer):
The persona engine should generate variations of the *existing* buyer profile with different levels of comfort with AI-driven customer outreach. The key variables are trust in AI communication, brand sensitivity (premium operators may be more protective), and current manual outreach processes.

### Glide Cleaners is the Rosetta Stone:
As the only non-pest-control customer, Glide's buying journey and usage patterns are disproportionately valuable. If Cameron has the transcript from that sale, it should be weighted heavily in understanding how the cross-vertical pitch lands differently.
