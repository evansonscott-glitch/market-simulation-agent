# Market Simulation Agent — Full Review

## Executive Summary

This review covers four critical dimensions of the simulation agent: (1) ensuring users provide proper context, (2) measuring statistically significant samples, (3) removing bias from experiments, and (4) handling different experiment formats correctly. The agent has strong foundations — anti-sycophancy architecture, stratified sampling, crash recovery — but has significant gaps in statistical rigor, context enforcement, format-specific measurement, and bias detection that undermine the reliability of its outputs.

---

## 1. Context Gathering — Are We Making Sure Users Provide Enough?

### What Works

- **5-stage conversational flow** (conversation_engine.py) walks users through idea, value prop, segments, assumptions, and data collection
- **Socratic method** prompts push users past surface-level descriptions
- **DATA_COLLECTION stage** explicitly asks for transcripts, call recordings, and customer data
- **Context quality tiers** are documented (C+ without data → B+ with full context)

### Critical Gaps

**GAP 1: No enforcement of minimum context quality.** The system happily runs a simulation with zero context files. The `ContextConfig` model makes everything optional with no warnings at launch time about degraded quality. A user can skip DATA_COLLECTION entirely and get a report that looks just as authoritative as one grounded in real data.

**GAP 2: No context quality score in the output.** The final report doesn't prominently display what context was and wasn't provided. A reader of the report has no way to know if it was grounded in real transcripts or pure LLM imagination.

**GAP 3: YAML path users bypass coaching entirely.** Users who write configs directly skip all five coaching stages. There's no equivalent validation that their product description is specific enough, their assumptions are testable, or their archetypes are well-defined.

**GAP 4: No validation of context file quality.** The system checks if files exist but not whether they contain meaningful content. An empty file or a one-line world model passes validation.

**GAP 5: World model truncation.** In `persona_engine.py:111`, world models are truncated to 6,000 chars and real customer data to 3,000 chars. There's no warning when this happens, and no strategy for prioritizing the most relevant sections.

### Recommendations

1. Add a `context_quality_score` to run metadata and report header (A/B/C/D/F based on what was provided)
2. Add minimum content length validation for context files (warn if < 500 chars)
3. Add a "config quality check" for YAML-path users that warns about vague descriptions, untestable assumptions, etc.
4. Surface truncation warnings prominently in the report methodology section
5. Make the report template dynamically adjust confidence language based on context quality

---

## 2. Statistical Significance — Are We Measuring Enough?

### What Works

- **Stratified sampling** via archetype weights ensures proportional representation
- **Market census engine** (market_census.py) identifies segmentation variables and builds weighted sample frames
- **Disposition distribution** ensures realistic skeptic/enthusiast ratios
- **Configurable sample size** (1-1000 personas)

### Critical Gaps

**GAP 6: No power analysis or minimum sample size guidance.** The default is 100 personas, but there's no calculation of whether this is sufficient to detect meaningful differences between segments. With 6 archetypes, some segments get only 10 personas — far too few for reliable sub-group analysis.

**GAP 7: No confidence intervals on any metric.** The report presents validation scores (1-5) and conversion rates as point estimates with no error bounds. A 60% conversion rate from 10 interviews is meaningless without a confidence interval (which would be ~30-90%).

**GAP 8: No statistical tests for segment differences.** The analysis engine claims to find "segment differences" but uses pure LLM judgment, not statistical tests. With n=15 per segment, the LLM might report that "Enterprise buyers were more skeptical" when the difference is pure noise.

**GAP 9: Batch analysis loses statistical power.** Interviews are analyzed in batches of 10 (`analysis_engine.py:379`), then insights are merged. This means the LLM sees local patterns within each batch but can't do proper cross-batch statistical comparison.

**GAP 10: No distinction between exploratory and confirmatory findings.** All findings are presented with equal authority. The report should distinguish between pre-registered hypotheses (assumptions) and emergent themes (which need separate validation).

**GAP 11: Scoring engine lacks variance reporting.** The `scoring_engine.py` reports averages but not standard deviations, making it impossible to know if a 0.6 composite score is consistently mediocre or wildly variable.

### Recommendations

1. Add a sample size calculator that recommends minimum personas based on number of segments and desired confidence level
2. Add confidence intervals to all percentage-based metrics (Wilson score interval for proportions)
3. Add standard deviation and variance to all aggregate scores
4. Add a statistical significance flag for segment comparisons (even a simple chi-square or proportion test)
5. Clearly label findings as "pre-registered hypothesis" vs "exploratory finding" in the report
6. Warn users when sub-segment sizes fall below statistical minimum (n < 20)

---

## 3. Bias Removal — Are We Getting Honest Results?

### What Works

- **Anti-sycophancy disposition model** forces ~40% skeptical/resistant personas
- **Red Team Skeptic archetype** (10% of sample) with forced skepticism 8-10
- **Per-archetype disposition overrides** prevent uniform enthusiasm
- **Persona prompts** explicitly instruct "DO NOT be a pushover"
- **Sycophancy detection** in the analysis engine flags artificially positive responses
- **Interviewer trained to stress-test** positive responses and explore skepticism

### Critical Gaps

**GAP 12: LLM-as-judge bias.** The same LLM (or model family) that generates persona responses also analyzes them for quality and sycophancy. This is like grading your own homework. The scoring engine (`scoring_engine.py`) uses the LLM to classify turns — if the LLM has a systematic bias, the scorer will share it.

**GAP 13: Anchoring bias in persona generation.** All personas in a batch are generated in a single LLM call with the same prompt. The LLM tends to generate personas that are variations on a theme rather than truly independent. Batch 1's personas may anchor batch 2's.

**GAP 14: Interviewer leading despite instructions.** The interviewer prompt says "don't ask leading questions" but the interviewer is also told to validate specific assumptions. This creates tension — the LLM may unconsciously steer conversations toward confirming the hypotheses it was told to test.

**GAP 15: No order effects control.** In focus groups (`focus_group.py:257`), persona order is randomized per round, which is good. But in standard interviews, all personas see the same questions in roughly the same order. There's no counterbalancing.

**GAP 16: Disposition is assigned but not verified.** A persona assigned "resistant" disposition might still give enthusiastic responses if the LLM overrides the prompt. There's no post-hoc check that personas actually behaved according to their assigned disposition.

**GAP 17: Monoculture bias.** All personas are generated by the same LLM with the same temperature. Real market segments have genuinely different communication styles, vocabulary, and reasoning patterns that a single model may not capture.

**GAP 18: No demand characteristics control.** In real experiments, subjects may behave differently because they know they're being studied (Hawthorne effect). The simulation equivalent: the LLM "knows" it's simulating a market test and may produce responses that feel like market research outputs rather than real human behavior.

### Recommendations

1. Add post-hoc disposition verification: check if personas labeled "resistant" actually showed resistance (measurable via sentiment scores)
2. Add inter-rater reliability: score a subset of interviews with a different model and compare
3. Add question order randomization for interviews (shuffle assumption/question order per persona)
4. Add a "bias audit" section to the report that quantifies observed vs. expected disposition adherence
5. Consider using different temperatures or model variants for different archetypes to increase response diversity
6. Add behavioral consistency scoring to flag personas whose responses don't match their profile

---

## 4. Experiment Format Validation — Does This Work for Every Format?

### Current Format Support

The system currently supports:
1. **Simulated 1:1 interviews** (interview_engine.py) — text-based Q&A
2. **Focus groups** (focus_group.py) — multi-persona round-robin discussion
3. **Multi-touch sequences** (temporal_sequence.py) — SMS/phone/email outreach over time
4. **Post-simulation chat** (post_sim_chat.py) — follow-up with individual personas

### Missing Format Considerations

**GAP 19: No "viewing a webpage" simulation.** If the user wants to test reactions to a landing page, product page, or web app demo, the system has no way to present visual/structural content. Interviews can describe a product verbally, but can't simulate the experience of scrolling a page, seeing pricing tables, or interacting with a UI. The persona has no visual context to react to.

**GAP 20: No "reading a PDF / document" simulation.** Similar to webpages — if the user wants to test a whitepaper, case study, pitch deck, or proposal, the system can't present the document structure, visuals, data tables, or formatting. The persona only gets a text description of what the document contains.

**GAP 21: No "filling out a form" simulation.** Form completion testing (sign-up flows, onboarding, surveys) requires simulating sequential field interactions, validation feedback, and drop-off behavior. The current interview format doesn't capture abandonment at specific fields, completion time, or field-level confusion.

**GAP 22: No "in-person interview" fidelity markers.** Real in-person interviews have body language, pauses, rapport-building, environmental factors, and interviewer bias from visual cues. The simulation doesn't account for these — it presents all findings as if they came from a sterile text environment. The report should acknowledge this limitation.

**GAP 23: No format-specific metrics.** Different formats need different KPIs:
- **Webpage**: Time-to-scroll, CTA click-through, bounce rate analog, above-fold comprehension
- **PDF**: Read-through rate, section-level engagement, call-to-action response
- **Form**: Completion rate, field-level drop-off, error rate, time-to-complete
- **In-person**: Rapport quality, non-verbal engagement proxy, interviewer effect estimation

**GAP 24: `interaction_context` is too coarse.** The three options (warm_demo, cold_outreach, blended) don't capture the format. A "warm_demo" could be a live product walkthrough, a recorded demo, a landing page, or a sales call — each with very different dynamics.

### Recommendations

1. Add an `experiment_format` config field with options: `interview`, `focus_group`, `webpage_review`, `document_review`, `form_test`, `sales_sequence`, `in_person_interview`
2. For `webpage_review` and `document_review`: accept a content summary/structure as input and inject it into persona context so they can react to specific sections
3. For `form_test`: add a sequential field-by-field simulation mode that tracks completion/abandonment
4. For `in_person_interview`: add a report caveat about text-only limitations and include questions about rapport/environment
5. Add format-specific metrics to the scoring engine
6. Add format-specific interviewer prompts (e.g., for webpage review: "Ask them what they noticed first, what confused them, what they'd click on")

---

## 5. Additional Issues Found

**GAP 25: Report doesn't distinguish simulation from reality.** The McKinsey-grade report format is polished enough that readers may treat simulated findings as equivalent to real market research. The disclaimers exist but are buried.

**GAP 26: No A/B testing support.** There's no built-in way to test two variants (pricing models, value props, landing pages) against each other with the same audience. Users would have to run two separate simulations and compare manually.

**GAP 27: No longitudinal consistency.** If a user runs the same simulation twice, they'll get different personas and potentially different conclusions. There's no seeding mechanism for reproducibility.

---

## Implementation Priority

| Priority | Gap | Impact | Effort |
|----------|-----|--------|--------|
| P0 | Context quality score in report (#1, #2) | High | Low |
| P0 | Confidence intervals on metrics (#7) | High | Medium |
| P0 | Sample size guidance (#6) | High | Medium |
| P0 | Experiment format support (#19-24) | High | Medium |
| P1 | Post-hoc disposition verification (#16) | Medium | Low |
| P1 | Statistical significance flags (#8) | Medium | Medium |
| P1 | Bias audit in report (#12, #14) | Medium | Medium |
| P1 | Variance reporting in scores (#11) | Medium | Low |
| P2 | Question order randomization (#15) | Low | Low |
| P2 | Context file quality validation (#4) | Low | Low |
| P2 | A/B testing support (#26) | Medium | High |
| P2 | Reproducibility seeding (#27) | Low | Medium |
