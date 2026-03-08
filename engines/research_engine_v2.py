"""
Research Engine v2 — RAG-Based World Model Generator

Replaces the v1 single-LLM-call approach with a multi-source pipeline:
  1. Query Generation — LLM generates targeted search queries
  2. Web Search — Executes queries against search APIs
  3. Content Extraction — Scrapes and extracts key facts from top results
  4. Fact Synthesis — Synthesizes facts into a cited world model

Every claim in the output world model is grounded in a verifiable source URL.
"""
import asyncio
import json
import re
import os
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from engines.logging_config import get_logger
from engines.llm_client import chat_completion, LLMRetryExhausted, LLMResponseEmpty
from engines.json_parser import parse_llm_json, JSONParseError

logger = get_logger(__name__)

# ──────────────────────────────────────────────
# Step 1: Query Generation
# ──────────────────────────────────────────────

def _generate_search_queries(product_name: str, product_description: str, target_market: str, model: str) -> List[str]:
    """
    Use an LLM to generate 10-15 targeted search queries for building the world model.
    """
    system_prompt = """You are a market research analyst preparing to build a comprehensive world model for a customer simulation.

Your job is to generate 12-15 specific, targeted search queries that will retrieve the most useful real-world data for grounding the simulation in reality.

## QUERY CATEGORIES (generate 2-3 queries per category):
1. **Market Size & Growth** — TAM, SAM, growth rates, industry revenue
2. **Competitive Landscape** — Key players, market share, alternatives
3. **Buyer Behavior** — How decisions are made, buying cycles, decision-makers
4. **Pricing & Economics** — Typical pricing, margins, customer acquisition costs
5. **Technology & Tools** — Current tech stack, adoption rates, integration landscape
6. **Pain Points & Trends** — Industry challenges, emerging trends, regulatory changes

## RULES
- Each query should be specific enough to return useful results (not generic)
- Include geographic qualifiers where relevant
- Include year qualifiers (2024 or 2025) for time-sensitive data
- Mix query types: some for articles, some for reports, some for statistics

Return a JSON array of strings, each being one search query. Return ONLY the JSON array."""

    user_prompt = f"""Generate search queries for this simulation:

**Product:** {product_name}
{product_description}

**Target Market:** {target_market}"""

    try:
        response = chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=model,
            temperature=0.4,
            max_tokens=2000,
        )
        queries = parse_llm_json(response, expected_type=list, context="search query generation")
        logger.info("Generated %d search queries", len(queries))
        return queries[:15]  # Cap at 15
    except (JSONParseError, LLMRetryExhausted, LLMResponseEmpty) as e:
        logger.error("Failed to generate search queries: %s", str(e)[:200])
        # Fallback: generate basic queries manually
        return _fallback_queries(product_name, target_market)


def _fallback_queries(product_name: str, target_market: str) -> List[str]:
    """Generate basic fallback queries if LLM query generation fails."""
    market_short = target_market[:80]
    return [
        f"{market_short} market size 2025",
        f"{market_short} industry overview",
        f"{market_short} competitive landscape",
        f"{market_short} buyer behavior",
        f"{market_short} pricing benchmarks",
        f"{market_short} technology stack tools",
        f"{market_short} pain points challenges",
        f"{market_short} industry trends 2025",
    ]


# ──────────────────────────────────────────────
# Step 2: Web Search
# ──────────────────────────────────────────────

def _search_web(query: str, num_results: int = 5) -> List[Dict[str, str]]:
    """
    Search the web using DuckDuckGo HTML search (no API key required).
    
    Returns a list of dicts with 'title', 'url', and 'snippet'.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        # Use DuckDuckGo HTML search
        params = {"q": query, "t": "h_", "ia": "web"}
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params=params,
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        
        for result in soup.select(".result"):
            title_elem = result.select_one(".result__title a, .result__a")
            snippet_elem = result.select_one(".result__snippet")
            
            if title_elem:
                url = title_elem.get("href", "")
                # DuckDuckGo wraps URLs in a redirect
                if "uddg=" in url:
                    url = requests.utils.unquote(url.split("uddg=")[-1].split("&")[0])
                
                title = title_elem.get_text(strip=True)
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
                
                if url and title and url.startswith("http"):
                    results.append({
                        "title": title,
                        "url": url,
                        "snippet": snippet,
                    })
        
        logger.debug("Search '%s': %d results", query[:50], len(results))
        return results[:num_results]
        
    except Exception as e:
        logger.warning("Search failed for '%s': %s", query[:50], str(e)[:100])
        return []


# ──────────────────────────────────────────────
# Step 3: Content Extraction
# ──────────────────────────────────────────────

def _scrape_page(url: str, timeout: int = 10) -> Optional[str]:
    """
    Scrape the text content from a URL.
    Returns the first ~5000 chars of meaningful text, or None on failure.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        
        # Check content type
        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type and "text/plain" not in content_type:
            logger.debug("Skipping non-text content: %s", content_type[:50])
            return None
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Remove script, style, nav, footer, header elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()
        
        # Extract text from article or main content area
        article = soup.find("article") or soup.find("main") or soup.find("body")
        if not article:
            return None
        
        text = article.get_text(separator="\n", strip=True)
        
        # Clean up excessive whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        
        # Return first 5000 chars (enough for fact extraction)
        if len(text) < 100:
            return None
            
        return text[:5000]
        
    except Exception as e:
        logger.debug("Scrape failed for %s: %s", url[:60], str(e)[:80])
        return None


def _extract_facts(
    page_text: str,
    url: str,
    title: str,
    product_name: str,
    target_market: str,
    model: str,
) -> List[Dict[str, str]]:
    """
    Use an LLM to extract verifiable facts from a scraped page.
    
    Returns a list of dicts with 'fact', 'source_url', 'source_title', 'confidence'.
    """
    system_prompt = f"""You are a research analyst extracting verifiable facts from a web page.

Your job is to extract specific, factual claims that are relevant to understanding the market for:
- Product: {product_name}
- Target Market: {target_market}

## RULES
1. Extract ONLY factual claims — numbers, statistics, named entities, specific descriptions.
2. Do NOT extract opinions, predictions, or marketing language.
3. Each fact should be a self-contained statement that can be verified.
4. If the page contains no relevant facts, return an empty array.
5. Rate your confidence in each fact: "high" (directly stated with data), "medium" (stated but without citation), "low" (inferred or approximate).

## OUTPUT FORMAT
Return a JSON array of objects:
[
  {{"fact": "The US residential roofing market was valued at $56.2 billion in 2023.", "confidence": "high"}},
  {{"fact": "The average roof replacement costs between $8,000 and $15,000.", "confidence": "medium"}}
]

Return ONLY the JSON array. If no relevant facts, return []."""

    user_prompt = f"""Extract relevant facts from this page:

**Source:** {title}
**URL:** {url}

**Content:**
{page_text[:4000]}"""

    try:
        response = chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=model,
            temperature=0.2,
            max_tokens=2000,
        )
        
        facts = parse_llm_json(response, expected_type=list, context=f"fact extraction from {url[:60]}")
        
        # Attach source metadata to each fact
        for fact in facts:
            if isinstance(fact, dict):
                fact["source_url"] = url
                fact["source_title"] = title
        
        logger.debug("Extracted %d facts from %s", len(facts), url[:60])
        return [f for f in facts if isinstance(f, dict) and "fact" in f]
        
    except (JSONParseError, LLMRetryExhausted, LLMResponseEmpty) as e:
        logger.debug("Fact extraction failed for %s: %s", url[:60], str(e)[:100])
        return []


# ──────────────────────────────────────────────
# Step 4: Synthesis
# ──────────────────────────────────────────────

def _synthesize_world_model(
    all_facts: List[Dict[str, str]],
    product_name: str,
    product_description: str,
    target_market: str,
    sources: List[Dict[str, str]],
    model: str,
) -> str:
    """
    Synthesize extracted facts into a structured, cited world model document.
    """
    # Build source index for citations
    source_index = {}
    for i, source in enumerate(sources, 1):
        source_index[source["url"]] = i
    
    # Format facts with citation numbers
    facts_text = ""
    for fact in all_facts:
        citation_num = source_index.get(fact.get("source_url", ""), "?")
        confidence = fact.get("confidence", "medium")
        facts_text += f"- [{confidence}] {fact['fact']} [Source {citation_num}]\n"
    
    # Build source list
    source_list = ""
    for i, source in enumerate(sources, 1):
        source_list += f"[{i}] {source['title']} — {source['url']}\n"
    
    system_prompt = f"""You are a senior market research analyst writing a world model briefing document.

You have been given a set of verified facts extracted from real web sources. Your job is to synthesize these facts into a comprehensive, well-structured briefing document.

## CRITICAL RULES
1. Use ONLY the facts provided below. Do NOT add any information from your own knowledge.
2. Every factual claim in your output MUST include a citation in the format [Source N].
3. If the facts don't cover a section well, say "Insufficient data from sources" rather than making something up.
4. Where facts conflict, note the discrepancy and cite both sources.
5. Include a confidence assessment for each section based on the quality and quantity of supporting facts.

## OUTPUT FORMAT
Write a structured Markdown document with these sections:
1. **Industry Overview** — Size, growth, key characteristics
2. **Competitive Landscape** — Key players, market dynamics
3. **Buyer Behavior & Decision-Making** — How purchases happen, who decides
4. **Pricing & Economics** — Typical pricing, margins, budget expectations
5. **Technology & Tools** — Current tech stack, adoption patterns
6. **Key Pain Points & Challenges** — What keeps buyers up at night
7. **Industry Trends** — What's changing, emerging opportunities
8. **Data Quality Assessment** — Honest assessment of what's well-supported vs. gaps
9. **Sources** — Full list of sources used

## FACTS FROM VERIFIED SOURCES
{facts_text}

## SOURCE INDEX
{source_list}"""

    user_prompt = f"""Synthesize a world model briefing for:

**Product:** {product_name}
{product_description}

**Target Market:** {target_market}

Use ONLY the verified facts provided. Cite every claim."""

    try:
        response = chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=model,
            temperature=0.3,
            max_tokens=6000,
        )
        
        # Append the raw source list at the bottom for reference
        response += f"\n\n---\n\n## Raw Source Index\n\n{source_list}"
        
        return response
        
    except (LLMRetryExhausted, LLMResponseEmpty) as e:
        logger.error("World model synthesis failed: %s", str(e)[:200])
        # Return a minimal document with just the raw facts
        return _fallback_synthesis(all_facts, sources, product_name, target_market)


def _fallback_synthesis(
    facts: List[Dict[str, str]],
    sources: List[Dict[str, str]],
    product_name: str,
    target_market: str,
) -> str:
    """Generate a fallback world model from raw facts when synthesis fails."""
    lines = [
        f"# World Model: {product_name} — {target_market}",
        "",
        "**Note:** AI synthesis failed. Below are the raw extracted facts.",
        "",
        "## Extracted Facts",
        "",
    ]
    for fact in facts:
        lines.append(f"- {fact.get('fact', 'N/A')} (Source: {fact.get('source_title', 'Unknown')})")
    
    lines.extend(["", "## Sources", ""])
    for i, source in enumerate(sources, 1):
        lines.append(f"[{i}] [{source['title']}]({source['url']})")
    
    return "\n".join(lines)


# ──────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────

def generate_world_model_v2(config: Dict[str, Any]) -> str:
    """
    Generate a world model using the RAG pipeline.
    
    Pipeline: Query Generation → Web Search → Content Scraping → Fact Extraction → Synthesis
    
    Args:
        config: The fully-resolved simulation config dict.
    
    Returns:
        A Markdown string containing the cited world model.
    """
    product_name = config["product_name"]
    product_description = config["product_description"]
    target_market = config["target_market"]
    model = config.get("llm_model", "gemini-2.5-flash")
    
    logger.info("=== Research Engine v2: Starting RAG pipeline ===")
    
    # Step 1: Generate search queries
    logger.info("Step 1/4: Generating search queries...")
    queries = _generate_search_queries(product_name, product_description, target_market, model)
    logger.info("Generated %d queries", len(queries))
    
    # Step 2: Execute searches
    logger.info("Step 2/4: Searching the web...")
    all_search_results = []
    seen_urls = set()
    
    for query in queries:
        results = _search_web(query, num_results=5)
        for r in results:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                all_search_results.append(r)
    
    logger.info("Found %d unique URLs across %d queries", len(all_search_results), len(queries))
    
    # Step 3: Scrape and extract facts
    logger.info("Step 3/4: Scraping pages and extracting facts...")
    all_facts = []
    successful_sources = []
    
    # Limit to top 20 URLs to keep it manageable
    for result in all_search_results[:20]:
        url = result["url"]
        title = result["title"]
        
        # Scrape the page
        page_text = _scrape_page(url)
        if not page_text:
            continue
        
        # Extract facts
        facts = _extract_facts(page_text, url, title, product_name, target_market, model)
        if facts:
            all_facts.extend(facts)
            successful_sources.append(result)
            logger.info("  %s: %d facts extracted", title[:50], len(facts))
    
    logger.info("Total: %d facts from %d sources", len(all_facts), len(successful_sources))
    
    # Handle case where we got no facts
    if not all_facts:
        logger.warning("RAG pipeline found no facts — falling back to v1 approach")
        from engines.research_engine import generate_world_model
        return generate_world_model(config)
    
    # Deduplicate facts (by content hash)
    unique_facts = []
    seen_hashes = set()
    for fact in all_facts:
        fact_hash = hashlib.md5(fact.get("fact", "").lower().encode()).hexdigest()
        if fact_hash not in seen_hashes:
            seen_hashes.add(fact_hash)
            unique_facts.append(fact)
    
    logger.info("After dedup: %d unique facts", len(unique_facts))
    
    # Step 4: Synthesize
    logger.info("Step 4/4: Synthesizing world model...")
    world_model = _synthesize_world_model(
        all_facts=unique_facts,
        product_name=product_name,
        product_description=product_description,
        target_market=target_market,
        sources=successful_sources,
        model=model,
    )
    
    logger.info("=== Research Engine v2: Complete (%d chars, %d sources) ===", len(world_model), len(successful_sources))
    
    return world_model


def ensure_world_model_v2(config: Dict[str, Any]) -> str:
    """
    Ensure a world model exists, using the v2 RAG pipeline if needed.
    
    If a world_model file is provided in the config, load it.
    Otherwise, generate one using the RAG pipeline.
    """
    from config import load_context_file
    
    world_model = load_context_file(config.get("world_model_path"))
    
    if world_model:
        logger.info("Using provided world model file (%d chars)", len(world_model))
        return world_model
    
    logger.info("No world model file provided — generating via RAG pipeline")
    world_model = generate_world_model_v2(config)
    
    # Save the generated world model
    output_dir = config.get("output_dir", ".")
    try:
        os.makedirs(output_dir, exist_ok=True)
        wm_path = os.path.join(output_dir, "world_model_v2.md")
        with open(wm_path, "w", encoding="utf-8") as f:
            f.write(world_model)
        logger.info("Saved RAG world model to: %s", wm_path)
    except IOError as e:
        logger.error("Failed to save world model: %s", e)
    
    config["_generated_world_model"] = world_model
    return world_model
