"""
Integration Test — All Four New Capabilities

Tests:
1. Graph Memory Engine — Build a knowledge graph from seed documents
2. Focus Group Mode — Run a moderated group discussion
3. Post-Simulation Chat — Interactive follow-up with a persona
4. Temporal Multi-Round Sequences — Multi-touch sales sequence with memory

Uses the Refinery Affiliate Slack Agent as the test product.
"""
import asyncio
import json
import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engines.graph_memory import build_knowledge_graph, KnowledgeGraph
from engines.focus_group import run_focus_group, format_focus_group_transcript
from engines.post_sim_chat import create_chat_session, chat, get_session_summary
from engines.temporal_sequence import (
    run_sequence, get_default_sales_sequence, format_sequence_result,
    analyze_sequence_batch, Touchpoint,
)
from engines.persona_engine import generate_personas
from engines.llm_client import chat_completion
from engines.logging_config import get_logger

logger = get_logger(__name__)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_features_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

MODEL = "gemini-2.5-flash"

PRODUCT_DESCRIPTION = """Refinery Affiliate is an AI-powered affiliate marketing analytics tool that helps
affiliate managers surface insights, identify opportunities for revenue growth and
margin expansion, find new affiliate partners, and detect fraud.

THE PIVOT BEING TESTED: Instead of a standalone SaaS dashboard that users must log
into, Refinery becomes an AI agent that lives in the affiliate manager's Slack
workspace. It connects to their affiliate network (Impact.com, CJ, AWIN, Rakuten),
proactively reviews their data in the background, and pushes actionable insights
directly into Slack — without the user ever having to log into a separate platform.

Pricing: $300-$1,000/month depending on programs managed."""

SEED_DOCUMENTS = {
    "product_overview": PRODUCT_DESCRIPTION,
    "market_context": """The affiliate marketing industry is valued at $17 billion globally (2023) 
and growing at 10% CAGR. Key platforms include Impact.com, CJ Affiliate, AWIN, and Rakuten.

The average affiliate manager spends 15-20 hours per week on manual data analysis 
and reporting. Tool fatigue is a major problem — the average marketing team uses 
12+ different SaaS tools.

Slack has 32.3 million daily active users. 77% of Fortune 100 companies use Slack.
The Slack app marketplace has 2,600+ integrations.

Key competitors in affiliate analytics: Affluent (acquired by Impact), Trackonomics, 
Affiverse, and manual spreadsheet workflows.

Common pain points for affiliate managers:
- Fraud detection is reactive, not proactive
- Dormant affiliates go unnoticed until revenue drops
- Cross-network reporting requires manual data aggregation
- New partner discovery is manual and time-consuming
- Performance anomalies are caught too late to act on""",
    "security_concerns": """Enterprise companies have strict requirements for third-party Slack integrations:
- SOC 2 Type II certification is typically required
- Data must be encrypted at rest and in transit
- OAuth 2.0 scopes must be minimally permissive
- IT security teams review all Slack bot permissions
- Some companies require on-premise or VPC deployment options
- GDPR compliance is required for EU-based affiliate data
- Average enterprise vendor approval process takes 4-12 weeks""",
}

CONFIG = {
    "product_description": PRODUCT_DESCRIPTION,
    "questions": [
        "What is your current process for reviewing affiliate program performance?",
        "Would you trust AI-generated alerts about your affiliates?",
        "What concerns do you have about connecting affiliate data to a Slack bot?",
    ],
    "assumptions": [
        "Affiliate managers prefer proactive Slack alerts over logging into a dashboard",
        "Trust in AI recommendations is high enough to act on alerts",
        "Data security concerns are manageable",
    ],
    "llm_model": MODEL,
    "focus_group_rounds": 4,
}

# Test personas — a diverse group for the focus group
TEST_PERSONAS = [
    {
        "name": "Sarah Chen",
        "title": "Senior Affiliate Manager",
        "company_type": "Mid-market DTC brand",
        "company_size": "200 employees",
        "industry": "E-commerce / Fashion",
        "years_experience": "6",
        "current_tools": "Impact.com, Google Sheets, manual Slack reporting",
        "pain_points": ["Spending 15+ hours/week on manual reporting", "Missing dormant affiliates", "No fraud detection"],
        "priorities": ["Time savings", "Revenue growth", "Fraud prevention"],
        "budget_sensitivity": "medium",
        "tech_sophistication": "medium",
        "disposition": "open",
        "skepticism_score": 4,
        "personality_notes": "Practical, data-driven, open to new tools if they prove ROI quickly",
    },
    {
        "name": "Marcus Williams",
        "title": "VP of Marketing",
        "company_type": "Enterprise retailer",
        "company_size": "5,000 employees",
        "industry": "Retail",
        "years_experience": "15",
        "current_tools": "CJ Affiliate, Tableau, internal BI tools",
        "pain_points": ["Vendor sprawl", "Data security concerns", "ROI measurement"],
        "priorities": ["Data governance", "Team efficiency", "Measurable ROI"],
        "budget_sensitivity": "low",
        "tech_sophistication": "high",
        "disposition": "cautious",
        "skepticism_score": 7,
        "personality_notes": "Executive mindset, asks tough ROI questions, concerned about security",
    },
    {
        "name": "Jess Rodriguez",
        "title": "Affiliate Manager",
        "company_type": "Performance marketing agency",
        "company_size": "50 employees",
        "industry": "Agency / Marketing Services",
        "years_experience": "4",
        "current_tools": "Impact.com, AWIN, Rakuten, multiple client dashboards",
        "pain_points": ["Managing 8 client programs simultaneously", "Context switching between platforms", "Client reporting"],
        "priorities": ["Efficiency", "Multi-client support", "Quick wins"],
        "budget_sensitivity": "high",
        "tech_sophistication": "medium",
        "disposition": "enthusiastic",
        "skepticism_score": 3,
        "personality_notes": "Energetic, always looking for shortcuts, values speed over perfection",
    },
    {
        "name": "David Park",
        "title": "Director of Partnerships",
        "company_type": "SaaS company",
        "company_size": "500 employees",
        "industry": "B2B SaaS",
        "years_experience": "10",
        "current_tools": "Impact.com, Salesforce, custom internal tools",
        "pain_points": ["Affiliate channel is secondary to direct sales", "Limited team bandwidth", "Hard to justify affiliate spend"],
        "priorities": ["Proving affiliate ROI to leadership", "Automation", "Partner quality"],
        "budget_sensitivity": "medium",
        "tech_sophistication": "high",
        "disposition": "skeptical",
        "skepticism_score": 6,
        "personality_notes": "Analytical, needs data to be convinced, has been burned by overpromising vendors",
    },
    {
        "name": "Linda Thompson",
        "title": "Senior Affiliate Analyst",
        "company_type": "Fortune 500 CPG company",
        "company_size": "20,000 employees",
        "industry": "Consumer Packaged Goods",
        "years_experience": "8",
        "current_tools": "CJ Affiliate, internal analytics platform, strict IT policies",
        "pain_points": ["12-week vendor approval process", "Can't install unapproved Slack bots", "Data sovereignty requirements"],
        "priorities": ["Compliance", "Security", "Incremental value over existing tools"],
        "budget_sensitivity": "low",
        "tech_sophistication": "high",
        "disposition": "resistant",
        "skepticism_score": 9,
        "personality_notes": "Process-oriented, will cite IT policies, represents the hardest enterprise buyer",
    },
]


def test_graph_memory():
    """Test 1: Build a knowledge graph from seed documents."""
    print("\n" + "=" * 60)
    print("TEST 1: GRAPH MEMORY ENGINE")
    print("=" * 60)

    start = time.time()
    graph = build_knowledge_graph(
        documents=SEED_DOCUMENTS,
        product_context=PRODUCT_DESCRIPTION,
        model=MODEL,
    )
    elapsed = time.time() - start

    print(f"\nGraph built in {elapsed:.1f}s")
    print(f"Stats: {json.dumps(graph.stats(), indent=2)}")

    # Test query
    context = graph.query_context("fraud detection affiliate")
    print(f"\nQuery 'fraud detection affiliate':\n{context[:500]}")

    # Test full summary
    summary = graph.get_full_context_summary(max_length=2000)
    print(f"\nFull summary ({len(summary)} chars):\n{summary[:500]}...")

    # Save
    graph.save(os.path.join(OUTPUT_DIR, "knowledge_graph.json"))

    # Save summary for other tests
    with open(os.path.join(OUTPUT_DIR, "graph_summary.md"), "w") as f:
        f.write(summary)

    print(f"\n✓ Graph Memory Engine: PASSED ({graph.stats()['entities']} entities, {graph.stats()['facts']} facts)")
    return graph


async def test_focus_group(graph: KnowledgeGraph):
    """Test 2: Run a focus group discussion."""
    print("\n" + "=" * 60)
    print("TEST 2: FOCUS GROUP ENGINE")
    print("=" * 60)

    graph_context = graph.get_full_context_summary(max_length=2000) if graph else ""

    start = time.time()
    result = await run_focus_group(
        personas=TEST_PERSONAS,
        config=CONFIG,
        group_id=1,
        graph_context=graph_context,
    )
    elapsed = time.time() - start

    print(f"\nFocus group completed in {elapsed:.1f}s")
    print(f"Turns: {len(result.transcript)}")
    print(f"Opinion shifts: {len(result.opinion_shifts)}")

    # Format and save transcript
    transcript_md = format_focus_group_transcript(result)
    with open(os.path.join(OUTPUT_DIR, "focus_group_transcript.md"), "w") as f:
        f.write(transcript_md)

    # Save raw data
    with open(os.path.join(OUTPUT_DIR, "focus_group_result.json"), "w") as f:
        json.dump(result.to_dict(), f, indent=2)

    # Print highlights
    if result.opinion_shifts:
        print("\nOpinion shifts detected:")
        for shift in result.opinion_shifts:
            print(f"  - {shift.persona_name}: {shift.from_stance} → {shift.to_stance} (trigger: {shift.trigger})")

    print(f"\nDynamics summary:\n{result.group_dynamics_summary[:500]}...")
    print(f"\n✓ Focus Group Engine: PASSED ({len(result.transcript)} turns, {len(result.opinion_shifts)} shifts)")
    return result


def test_post_sim_chat(focus_group_result):
    """Test 3: Post-simulation chat with a persona from the focus group."""
    print("\n" + "=" * 60)
    print("TEST 3: POST-SIMULATION CHAT ENGINE")
    print("=" * 60)

    # Pick the most skeptical persona for the most interesting chat
    persona = TEST_PERSONAS[3]  # David Park — the skeptic
    name = persona["name"]

    # Build transcript from focus group
    fg_dict = focus_group_result.to_dict()
    transcript_text = "\n".join(
        f"{t.get('speaker', 'Unknown')}: {t.get('content', '')}"
        for t in fg_dict.get("transcript", [])
    )

    session = create_chat_session(
        persona=persona,
        simulation_transcript=transcript_text,
        simulation_type="focus_group",
        model=MODEL,
    )

    # Simulate a founder probing the skeptic
    probe_questions = [
        f"Hey {name}, thanks for the candid feedback in the focus group. You seemed hesitant about the Slack approach. What would it actually take to get you to try this?",
        "What if we offered a 30-day free pilot where we connect to your Impact.com data in a sandboxed environment — no Slack integration needed initially, just a daily email digest of insights?",
        "If the pilot showed you were missing $50K+ in revenue from dormant affiliates, would that be enough to justify going through the vendor approval process?",
    ]

    start = time.time()
    for question in probe_questions:
        print(f"\n> You: {question}")
        response = chat(session, question)
        print(f"> {name}: {response}")
    elapsed = time.time() - start

    # Save session
    summary = get_session_summary(session)
    with open(os.path.join(OUTPUT_DIR, "post_sim_chat.md"), "w") as f:
        f.write(summary)

    session.save(os.path.join(OUTPUT_DIR, "post_sim_chat_session.json"))

    print(f"\n✓ Post-Sim Chat Engine: PASSED ({len(session.exchanges)} exchanges in {elapsed:.1f}s)")
    return session


def test_temporal_sequence():
    """Test 4: Multi-touch sales sequence with memory."""
    print("\n" + "=" * 60)
    print("TEST 4: TEMPORAL MULTI-ROUND SEQUENCE ENGINE")
    print("=" * 60)

    # Use a 3-touch sequence for speed (the full 5-touch would take longer)
    touchpoints = [
        Touchpoint(
            round_num=1,
            channel="sms",
            timing_label="Day 1",
            context="Initial outreach. You found this person through a conference attendee list.",
            agent_objective="Introduce Refinery and gauge interest. Get a response.",
            max_turns=3,
        ),
        Touchpoint(
            round_num=2,
            channel="email",
            timing_label="Day 4",
            context="Follow-up. They may or may not have responded to the initial text.",
            agent_objective="Share a specific insight about their affiliate program (e.g., competitor data). Get them to book a demo.",
            max_turns=2,
        ),
        Touchpoint(
            round_num=3,
            channel="phone_call",
            timing_label="Day 8",
            context="Phone follow-up. Escalating to a direct conversation.",
            agent_objective="Have a real conversation. Understand their specific pain points. Close on a pilot.",
            max_turns=3,
        ),
    ]

    # Run sequences for 3 personas with different dispositions
    test_personas = [TEST_PERSONAS[0], TEST_PERSONAS[2], TEST_PERSONAS[3]]  # open, enthusiastic, skeptical

    start = time.time()
    results = []
    for persona in test_personas:
        print(f"\nRunning sequence for {persona['name']} ({persona['disposition']})...")
        result = run_sequence(
            persona=persona,
            touchpoints=touchpoints,
            product_description=PRODUCT_DESCRIPTION,
            model=MODEL,
        )
        results.append(result)
        print(f"  → {result.final_outcome} (turns: {result.total_turns})")

    elapsed = time.time() - start

    # Save individual transcripts
    for result in results:
        name_slug = result.persona["name"].lower().replace(" ", "_")
        transcript_md = format_sequence_result(result)
        with open(os.path.join(OUTPUT_DIR, f"sequence_{name_slug}.md"), "w") as f:
            f.write(transcript_md)

    # Aggregate analysis
    analysis = analyze_sequence_batch(results)
    with open(os.path.join(OUTPUT_DIR, "sequence_analysis.json"), "w") as f:
        json.dump(analysis, f, indent=2)

    print(f"\nAggregate analysis:")
    print(f"  Conversion rate: {analysis['conversion_rate']:.0%}")
    print(f"  Outcomes: {json.dumps(analysis['outcomes'])}")
    print(f"  Top objections: {json.dumps(analysis.get('top_objections', {}), indent=2)}")
    print(f"  Channel effectiveness: {json.dumps(analysis.get('channel_effectiveness', {}), indent=2)}")

    # Save all results
    with open(os.path.join(OUTPUT_DIR, "sequence_results.json"), "w") as f:
        json.dump([r.to_dict() for r in results], f, indent=2)

    print(f"\n✓ Temporal Sequence Engine: PASSED ({len(results)} sequences, {elapsed:.1f}s)")
    return results


async def main():
    """Run all four integration tests."""
    print("=" * 60)
    print("INTEGRATION TEST: ALL FOUR NEW CAPABILITIES")
    print("=" * 60)
    print(f"Product: Refinery Affiliate Slack Agent")
    print(f"Model: {MODEL}")
    print(f"Output: {OUTPUT_DIR}")

    total_start = time.time()

    # Test 1: Graph Memory
    graph = test_graph_memory()

    # Test 2: Focus Group (uses graph)
    fg_result = await test_focus_group(graph)

    # Test 3: Post-Sim Chat (uses focus group result)
    chat_session = test_post_sim_chat(fg_result)

    # Test 4: Temporal Sequences (independent)
    seq_results = test_temporal_sequence()

    total_elapsed = time.time() - total_start

    # Summary
    print("\n" + "=" * 60)
    print("INTEGRATION TEST SUMMARY")
    print("=" * 60)
    print(f"Total time: {total_elapsed:.1f}s")
    print(f"Graph Memory: {graph.stats()['entities']} entities, {graph.stats()['facts']} facts")
    print(f"Focus Group: {len(fg_result.transcript)} turns, {len(fg_result.opinion_shifts)} opinion shifts")
    print(f"Post-Sim Chat: {len(chat_session.exchanges)} exchanges")
    print(f"Temporal Sequences: {len(seq_results)} sequences completed")
    print(f"\nAll output saved to: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
