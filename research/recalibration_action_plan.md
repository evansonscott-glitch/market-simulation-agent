# Simulation Agent Recalibration: Action Plan

**To:** Scott
**From:** Manus AI
**Date:** February 25, 2026
**Subject:** Action Plan to Recalibrate the Simulation Agent for Accuracy and Realism

## 1. Objective

This document outlines a comprehensive action plan to address the three core failure modes identified in the audit of the v1 simulation report: **(1) Sycophancy Bias, (2) Hallucinated Statistics, and (3) World Model Gaps.** The goal is to re-engineer the agent to produce a significantly more accurate, reliable, and useful report by grounding it in verifiable data and realistic human behavior.

This plan will be executed in a series of sequential phases, culminating in a re-run of the simulation and a comparative analysis to measure improvement.

---

## 2. The Recalibration Plan

### Phase 1: Build a Grounded World Model

**Problem:** The agent's knowledge was based on the general LLM training data, leading to factual errors about the competitive landscape and market data.

**Solution:** We will create a structured, verifiable, and explicit knowledge base (the "World Model") that the agent **must** use as its single source of truth for all factual claims. This model will be a collection of structured data files (JSON or YAML) containing:

*   **Market Data:** Verified churn rate benchmarks, company size distributions, and technology adoption rates for pest control and lawn care.
*   **Competitor Profiles:** Detailed profiles for each real competitor (e.g., VOZIQ AI, ServiceTitan), including their pricing, features, and target market.
*   **CRM Database:** A list of all relevant CRMs (Jobber, FieldRoutes, etc.) with their market share, pricing, and integration capabilities.
*   **Pricing Benchmarks:** Real-world pricing for comparable SaaS tools in the home services industry.

**Action Steps:**
1.  Conduct deep research to populate the World Model with sourced and verified data.
2.  Structure this data into machine-readable files.
3.  Modify the agent's core logic to query this World Model for any factual information, rather than relying on its internal knowledge.

### Phase 2: Recalibrate the Persona & Interview Engines

**Problem:** The AI personas were too agreeable, leading to unrealistic validation rates and a lack of critical feedback.

**Solution:** We will re-engineer the persona generation and interview process to explicitly introduce skepticism and eliminate sycophantic bias.

**Action Steps:**
1.  **Introduce a "Skepticism Score":** Each generated persona will be assigned a skepticism score (e.g., from 1-10) based on their archetype. Data-Hungry Operators and Competitive Evaluators will have higher scores, while Overwhelmed Founders will have lower scores. This score will directly influence their responses.
2.  **Create a "Red Team Skeptic" Archetype:** We will add a sixth archetype whose sole purpose is to be critical. This persona will be programmed to find flaws, question the value proposition, and represent the most difficult buyers. We will allocate 10-15% of the audience to this archetype.
3.  **Modify Persona Generation Prompts:** The prompts used to create personas will be updated with explicit negative constraints, such as: "This persona is busy and skeptical. They are not easily impressed. Do not make them overly agreeable. They should push back on the interviewer and raise objections based on their profile."
4.  **Constrain Hallucination in Interviews:** The interview engine will be modified to prevent the agent from inventing statistics. The prompt for the interviewer will include a new rule: "You must not invent any statistics or quantitative claims. If you need to cite data, you must query the World Model. If the data is not in the World Model, you must state, 'This is a hypothesis we are testing.'"

### Phase 3: Recalibrate the Analysis Engine

**Problem:** The v1 report used arbitrary, meaningless metrics like "Problem Resonance," which created a false sense of scientific rigor.

**Solution:** We will replace these metrics with concrete, measurable, and defensible outputs based directly on the interview content.

**Action Steps:**
1.  **Eliminate Arbitrary Scores:** The "Problem Resonance" and "Solution Fit" scores will be removed entirely.
2.  **Introduce Concrete Metrics:** The analysis engine will instead calculate and report on:
    *   **Objection Rate:** The percentage of interviews in which a specific objection (e.g., price, integration) was raised.
    *   **Unprompted Feature Mentions:** The number of times a specific feature (e.g., automated outreach) was mentioned by the persona without being prompted by the interviewer.
    *   **Sentiment Shift:** Track the persona's sentiment from the beginning to the end of the interview to measure the impact of the pitch.
3.  **Focus on Qualitative Themes:** The report will de-emphasize scores and instead focus on surfacing the most common qualitative themes, direct quotes, and patterns of objections and buying triggers.

### Phase 4: Re-run Simulation and Compare Results

**Problem:** We need to validate that the recalibration was successful.

**Solution:** We will re-run the full 100-persona simulation using the recalibrated agent and then conduct a comparative analysis of the v1 and v2 reports.

**Action Steps:**
1.  Regenerate the 100-persona audience using the recalibrated Persona Engine.
2.  Execute the full simulation using the recalibrated Interview and Analysis Engines.
3.  Create a comparative report that shows a side-by-side analysis of:
    *   v1 vs. v2 validation rates.
    *   v1 vs. v2 sentiment analysis (expecting a much higher negative/neutral sentiment in v2).
    *   v1 vs. v2 objection analysis (expecting a higher volume and diversity of objections in v2).
    *   A qualitative assessment of the realism and usefulness of the v2 report compared to v1.

---

## 3. Expected Outcome

The successful execution of this plan will result in a Simulation Agent v2 that is significantly more accurate, reliable, and useful. The final report will be grounded in real-world data, reflect realistic customer skepticism, and provide a trustworthy foundation for strategic decision-making. This will transform the agent from a promising prototype into a powerful, defensible tool for the Philo Ventures portfolio.
