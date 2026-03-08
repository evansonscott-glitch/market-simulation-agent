---
name: user-simulation
description: Run an iterative, self-improving user simulation to test a product, agent, or GTM idea. Use when the user wants to simulate user/customer interactions, test assumptions, or generate a knowledge base for an agent.
---

# User Simulation Skill

This skill enables Manus to run an iterative, self-improving user simulation loop, modeled on Andrej Karpathy’s “autoresearch” concept. It is designed to test a product, agent, or go-to-market strategy against a set of simulated user personas, score the results against a defined rubric, and iteratively refine the inputs until the simulation realistically mirrors real-world behavior.

## Core Workflow

The simulation process follows a six-step, iterative loop:

1.  **Define the World Model:** Gather the necessary context for the simulation. This is the most critical step and requires a conversational approach with the user to gather the right inputs.
2.  **Define the Scoring Function:** Establish a clear, measurable rubric for what “better” looks like. This is grounded in real data where possible.
3.  **Run the Simulation:** Generate multi-turn conversations between the agent/product and the simulated user personas across a set of defined triggers.
4.  **Score the Results:** Score each conversation against the rubric to identify gaps between the simulation and the desired outcome.
5.  **Revise and Refine:** Analyze the lowest-scoring dimensions and revise the inputs (personas, agent playbooks, trigger framing) to close the gaps.
6.  **Commit and Iterate:** Commit the improved knowledge base with a version number and changelog, then repeat the loop until the simulation reaches a desired level of fidelity.

---

## Step 1: Define the World Model (Input Gathering)

Before running any simulation, you must gather the necessary context. Use a conversational approach to ask the user for the following inputs. Do not ask for them all at once; gather them progressively.

### Data Gathering Checklist:

| Input | Description | Priority | Why It Matters |
|---|---|---|---|
| **Real Transcripts** | Actual call recordings, SMS threads, or email chains with real users/customers. | **Critical** | This is the ground truth. The simulation’s primary goal is to statistically match the patterns in these transcripts. |
| **CRM Data** | Customer relationship management data (e.g., from JobNimbus, Salesforce). | High | Provides quantitative data on customer segments, job values, conversion rates, and service history. |
| **The Product/Agent** | A clear definition of what is being simulated (the product, the AI agent, the sales rep). | High | Defines one side of the conversation. |
| **The Goal** | What is the desired outcome of the interaction (e.g., book an appointment, make a purchase, resolve a support ticket)? | High | Defines the “win” condition for the simulation. |
| **Triggers** | The specific events that initiate the interaction (e.g., a user signs up, a storm hits a customer’s zip code). | High | Defines the context for the conversation. |
| **Market Research** | Any existing research on the target audience, market dynamics, or competitive landscape. | Medium | Helps build more realistic personas when real transcript data is limited. |
| **Competitor Analysis** | How do competitors talk to their customers? What are their value propositions? | Medium | Provides context for how users perceive the market. |

**If real transcripts are not available, you MUST inform the user that the simulation will be based on a *proxy* model and will have lower fidelity.**

---

## Step 2: Define the Scoring Function

Once the world model is defined, you must establish the scoring function. The default scoring rubric is located in `references/scoring_rubric.md`. Read this file to understand the 7 dimensions of the rubric.

**Action:** Read `/home/ubuntu/skills/user-simulation/references/scoring_rubric.md`.

Propose the scoring rubric to the user and get their buy-in before proceeding. If the user wants to adjust the rubric (e.g., add a dimension, change a weight), incorporate their feedback.

---

## Step 3: Run the Simulation

With the world model and scoring function defined, run the simulation. This typically involves using the `map` tool to generate a batch of conversations in parallel.

**Key considerations:**

*   **Persona Diversity:** Ensure the simulation covers a representative sample of the defined user archetypes.
*   **Trigger Variants:** For each trigger, generate 3-5 variations (different framing, different urgency) to test which ones perform best.
*   **Outcome Targets:** Simulate a mix of successful, moderate, and unsuccessful outcomes to understand the full range of user behavior.

---

## Step 4: Score the Results

After the simulation run is complete, score each conversation against the agreed-upon rubric. This will produce a set of quantitative scores for each of the 7 dimensions.

**Action:** Create a table or spreadsheet that summarizes the scores for each conversation and calculates the average score for each dimension across the entire batch.

---

## Step 5: Revise and Refine

Analyze the scoring results to identify the biggest gaps between the simulation and the desired outcome.

*   **Identify the lowest-scoring dimensions.** For example, if “Persona Consistency” is consistently low, it means the persona definitions need to be improved.
*   **Formulate a hypothesis for improvement.** For example, “The ‘Retiree’ persona is not price-sensitive enough. I will revise the persona to include a stronger emphasis on fixed-income budget constraints.”
*   **Revise the inputs.** Update the persona definitions, agent playbooks, or trigger framing based on your hypothesis.

---

## Step 6: Commit and Iterate

Commit the revised inputs and the new simulation results as a new version of the knowledge base.

**Versioning:**

*   Use a simple version number (e.g., v1.1, v1.2).
*   Include a plain-language summary of what changed and why (e.g., “v1.2 — Increased price sensitivity in Retiree persona to better match real-world budget objections.”).

**The Loop:** After committing the changes, repeat the process from Step 3. The goal is to see the scores on each dimension improve with each iteration, indicating that the simulation is becoming a more accurate proxy for reality.

This iterative process transforms the simulation from a one-time snapshot into a durable, compounding research asset.
