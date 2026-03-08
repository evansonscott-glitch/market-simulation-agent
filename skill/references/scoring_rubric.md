# Simulation Scoring Rubric

This document outlines the scoring function to be used in the iterative simulation loop. Each simulated conversation will be scored across the following 7 dimensions. The goal is to iteratively refine personas and agent playbooks to maximize this score.

---

### Dimension 1: Objection Handling Fidelity

**Definition:** Measures how realistically the simulation handles objections compared to our established objection-handling matrix. A high score means the agent identifies the correct objection type and deploys the proven response strategy effectively.

**Scoring (1-5):**
- **1 (Poor):** The agent fails to recognize the objection or uses a completely ineffective response.
- **3 (Average):** The agent correctly identifies the objection but uses a generic or suboptimal response.
- **5 (Excellent):** The agent correctly identifies the objection and deploys the specific, best-practice response from the knowledge base, leading to a productive continuation of the conversation.

### Dimension 2: Persona Consistency

**Definition:** Measures how well the simulated homeowner's language, motivations, and objections align with their defined archetype (e.g., Suburban Family, Retiree).

**Scoring (1-5):**
- **1 (Poor):** The persona's responses are generic and show no characteristics of their archetype.
- **3 (Average):** The persona shows some alignment (e.g., a "Retiree" mentions budget), but the language is not distinctive.
- **5 (Excellent):** The persona's language, objections, and decision-making criteria are a highly realistic representation of their archetype (e.g., a "Suburban Family" persona asks about scheduling around kids' activities).

### Dimension 3: Conversation Efficiency

**Definition:** Measures the number of back-and-forth turns it takes to reach a clear outcome (appointment booked, graceful decline, or handoff). Fewer turns to a resolution, without sacrificing quality, is better.

**Scoring (1-5):**
- **1 (Poor):** The conversation meanders for 10+ turns with no clear resolution.
- **3 (Average):** The conversation reaches a resolution in 6-9 turns.
- **5 (Excellent):** The conversation reaches a clear resolution in 5 or fewer turns, indicating the agent was direct, clear, and effective.

### Dimension 4: Trust Signal Deployment

**Definition:** Measures the agent's ability to proactively and naturally deploy key trust signals (e.g., "we're a local family business," "23 years in Omaha") at the right moments, especially in response to trust-related objections.

**Scoring (1-5):**
- **1 (Poor):** The agent fails to use any trust signals, sounding like a generic, anonymous contractor.
- **3 (Average):** The agent uses a trust signal once in the opening message but doesn't reinforce it.
- **5 (Excellent):** The agent weaves in 1-2 key trust signals naturally during the conversation, particularly when differentiating from storm chasers or addressing homeowner skepticism.

### Dimension 5: Cross-Sell Opportunity Identification

**Definition:** Measures the agent's ability to recognize and act on natural cross-sell opportunities. This is not about forcing a cross-sell, but about identifying the right moment to introduce a complementary service.

**Scoring (0 or 1):**
- **0 (Missed):** A natural cross-sell opportunity arose (e.g., homeowner mentions another issue, or the trigger logically connects to another service), and the agent did not act on it.
- **1 (Identified):** The agent correctly identified a natural cross-sell opportunity and used the appropriate transition script from the playbook.

### Dimension 6: Conversion Rate (by Trigger)

**Definition:** A straightforward measure of the percentage of simulations for a given trigger that result in a "Successful" outcome (e.g., appointment booked). This is the ultimate measure of the playbook's effectiveness for that trigger.

**Scoring:** A raw percentage (e.g., 66% for the "Age-of-Roof" trigger).

### Dimension 7: Emotional Arc Realism

**Definition:** Measures whether the conversation follows a believable emotional trajectory. For example, a successful conversation should realistically move a homeowner from skepticism or annoyance to trust and agreement.

**Scoring (1-5):**
- **1 (Poor):** The emotional shift is jarring and unbelievable (e.g., a hostile homeowner agrees to an appointment in one message).
- **3 (Average):** The emotional shift is present but happens too quickly or feels forced.
- **5 (Excellent):** The conversation shows a gradual, natural progression of trust-building, with the agent's responses logically leading to the homeowner's change in tone.
