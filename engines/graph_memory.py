"""
Graph Memory Engine — Lightweight Knowledge Graph for Agent Grounding

Extracts entities, relationships, and facts from seed documents (company data,
market research, transcripts, product specs) and builds a structured knowledge
graph that agents can query during simulation.

Inspired by MiroFish's Zep-based GraphRAG, but implemented as a zero-dependency
JSON graph that runs locally without external services.

Key features:
  - Entity extraction from multiple document types
  - Relationship mapping between entities
  - Fact indexing with source attribution
  - Query interface for agents to retrieve relevant context
  - Serialization to/from JSON for persistence
"""
import json
import hashlib
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict

from engines.logging_config import get_logger
from engines.llm_client import chat_completion, LLMRetryExhausted, LLMResponseEmpty
from engines.json_parser import parse_llm_json, JSONParseError

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Data Structures
# ──────────────────────────────────────────────

@dataclass
class Entity:
    """A node in the knowledge graph."""
    id: str
    name: str
    entity_type: str  # person, company, product, market, technology, concept
    attributes: Dict[str, Any] = field(default_factory=dict)
    source_documents: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Relationship:
    """An edge in the knowledge graph."""
    source_id: str
    target_id: str
    relationship_type: str  # competes_with, uses, serves, part_of, etc.
    description: str = ""
    weight: float = 1.0
    source_document: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Fact:
    """A verified or sourced fact attached to entities."""
    id: str
    content: str
    entity_ids: List[str] = field(default_factory=list)
    source_document: str = ""
    confidence: float = 1.0  # 1.0 = from real data, 0.5 = inferred
    category: str = ""  # pricing, market_size, pain_point, competitor, etc.

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class KnowledgeGraph:
    """
    Lightweight in-memory knowledge graph.

    Stores entities, relationships, and facts with efficient lookup
    by entity type, relationship type, and keyword search.
    """

    def __init__(self):
        self.entities: Dict[str, Entity] = {}
        self.relationships: List[Relationship] = []
        self.facts: Dict[str, Fact] = {}
        self._entity_index: Dict[str, Set[str]] = defaultdict(set)  # type -> entity_ids
        self._relationship_index: Dict[str, List[int]] = defaultdict(list)  # entity_id -> relationship indices
        self._fact_index: Dict[str, List[str]] = defaultdict(list)  # entity_id -> fact_ids

    def add_entity(self, entity: Entity) -> None:
        """Add an entity to the graph."""
        self.entities[entity.id] = entity
        self._entity_index[entity.entity_type].add(entity.id)

    def add_relationship(self, rel: Relationship) -> None:
        """Add a relationship to the graph."""
        idx = len(self.relationships)
        self.relationships.append(rel)
        self._relationship_index[rel.source_id].append(idx)
        self._relationship_index[rel.target_id].append(idx)

    def add_fact(self, fact: Fact) -> None:
        """Add a fact to the graph."""
        self.facts[fact.id] = fact
        for eid in fact.entity_ids:
            self._fact_index[eid].append(fact.id)

    def get_entities_by_type(self, entity_type: str) -> List[Entity]:
        """Get all entities of a specific type."""
        return [self.entities[eid] for eid in self._entity_index.get(entity_type, set())
                if eid in self.entities]

    def get_entity_relationships(self, entity_id: str) -> List[Tuple[Relationship, Entity]]:
        """Get all relationships for an entity, with the connected entity."""
        results = []
        for idx in self._relationship_index.get(entity_id, []):
            rel = self.relationships[idx]
            other_id = rel.target_id if rel.source_id == entity_id else rel.source_id
            if other_id in self.entities:
                results.append((rel, self.entities[other_id]))
        return results

    def get_entity_facts(self, entity_id: str) -> List[Fact]:
        """Get all facts associated with an entity."""
        return [self.facts[fid] for fid in self._fact_index.get(entity_id, [])
                if fid in self.facts]

    def query_context(self, query: str, max_results: int = 10) -> str:
        """
        Simple keyword-based context retrieval for agent grounding.

        Returns a formatted string of relevant facts and relationships
        that agents can use in their system prompts.
        """
        query_lower = query.lower()
        query_terms = set(query_lower.split())

        # Score entities by keyword relevance
        scored_entities = []
        for eid, entity in self.entities.items():
            score = 0
            entity_text = f"{entity.name} {entity.entity_type} {json.dumps(entity.attributes)}".lower()
            for term in query_terms:
                if term in entity_text:
                    score += 1
            if score > 0:
                scored_entities.append((score, eid))

        scored_entities.sort(reverse=True)
        top_entity_ids = [eid for _, eid in scored_entities[:max_results]]

        # Score facts by keyword relevance
        scored_facts = []
        for fid, fact in self.facts.items():
            score = 0
            fact_text = f"{fact.content} {fact.category}".lower()
            for term in query_terms:
                if term in fact_text:
                    score += 1
            # Boost facts connected to top entities
            for eid in fact.entity_ids:
                if eid in top_entity_ids:
                    score += 2
            if score > 0:
                scored_facts.append((score, fid))

        scored_facts.sort(reverse=True)
        top_facts = [self.facts[fid] for _, fid in scored_facts[:max_results]]

        # Format output
        lines = []
        if top_entity_ids:
            lines.append("## Relevant Entities")
            for eid in top_entity_ids[:5]:
                entity = self.entities[eid]
                attrs = ", ".join(f"{k}: {v}" for k, v in entity.attributes.items())
                lines.append(f"- **{entity.name}** ({entity.entity_type}): {attrs}")

                # Add relationships
                rels = self.get_entity_relationships(eid)
                for rel, other in rels[:3]:
                    lines.append(f"  → {rel.relationship_type} → {other.name}")

        if top_facts:
            lines.append("\n## Relevant Facts")
            for fact in top_facts[:8]:
                source = f" [Source: {fact.source_document}]" if fact.source_document else ""
                lines.append(f"- {fact.content}{source}")

        return "\n".join(lines) if lines else "No relevant context found in knowledge graph."

    def get_full_context_summary(self, max_length: int = 4000) -> str:
        """
        Generate a comprehensive summary of the entire knowledge graph
        for injection into agent system prompts.
        """
        lines = []

        # Entity summary by type
        for entity_type, entity_ids in sorted(self._entity_index.items()):
            entities = [self.entities[eid] for eid in entity_ids if eid in self.entities]
            if entities:
                lines.append(f"\n## {entity_type.replace('_', ' ').title()}s")
                for entity in entities[:10]:
                    attrs = ", ".join(f"{k}: {v}" for k, v in list(entity.attributes.items())[:5])
                    lines.append(f"- **{entity.name}**: {attrs}")

        # Key facts by category
        facts_by_category = defaultdict(list)
        for fact in self.facts.values():
            facts_by_category[fact.category or "general"].append(fact)

        for category, facts in sorted(facts_by_category.items()):
            lines.append(f"\n## {category.replace('_', ' ').title()}")
            for fact in facts[:8]:
                lines.append(f"- {fact.content}")

        summary = "\n".join(lines)
        if len(summary) > max_length:
            summary = summary[:max_length] + "\n\n[... truncated for length]"
        return summary

    def stats(self) -> Dict[str, Any]:
        """Return graph statistics."""
        return {
            "entities": len(self.entities),
            "relationships": len(self.relationships),
            "facts": len(self.facts),
            "entity_types": {k: len(v) for k, v in self._entity_index.items()},
            "fact_categories": dict(defaultdict(int, {
                f.category: 1 for f in self.facts.values()
            })),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the graph to a dict for JSON persistence."""
        return {
            "entities": {eid: e.to_dict() for eid, e in self.entities.items()},
            "relationships": [r.to_dict() for r in self.relationships],
            "facts": {fid: f.to_dict() for fid, f in self.facts.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeGraph":
        """Deserialize a graph from a dict."""
        graph = cls()
        for eid, edata in data.get("entities", {}).items():
            graph.add_entity(Entity(**edata))
        for rdata in data.get("relationships", []):
            graph.add_relationship(Relationship(**rdata))
        for fid, fdata in data.get("facts", {}).items():
            graph.add_fact(Fact(**fdata))
        return graph

    def save(self, path: str) -> None:
        """Save graph to a JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info("Knowledge graph saved to %s (%s)", path, self.stats())

    @classmethod
    def load(cls, path: str) -> "KnowledgeGraph":
        """Load graph from a JSON file."""
        with open(path) as f:
            data = json.load(f)
        graph = cls.from_dict(data)
        logger.info("Knowledge graph loaded from %s (%s)", path, graph.stats())
        return graph


# ──────────────────────────────────────────────
# Graph Builder — LLM-powered extraction
# ──────────────────────────────────────────────

def _generate_entity_id(name: str, entity_type: str) -> str:
    """Generate a deterministic ID for an entity."""
    raw = f"{entity_type}:{name.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _generate_fact_id(content: str) -> str:
    """Generate a deterministic ID for a fact."""
    return hashlib.md5(content.lower().strip().encode()).hexdigest()[:12]


def _extract_from_document(
    document_text: str,
    document_name: str,
    product_context: str,
    model: str,
) -> Dict[str, Any]:
    """
    Use LLM to extract entities, relationships, and facts from a single document.
    """
    system_prompt = f"""You are a knowledge graph extraction engine. Your job is to extract
structured information from documents to build a knowledge graph for market simulation.

## PRODUCT CONTEXT
{product_context}

## EXTRACTION RULES
1. Extract REAL entities mentioned in the document — companies, people, products, technologies, markets, concepts.
2. Extract REAL relationships between entities — competes_with, uses, serves, part_of, acquired_by, etc.
3. Extract VERIFIABLE facts — statistics, prices, market sizes, dates, quotes, claims with evidence.
4. DO NOT invent or hallucinate. Only extract what is explicitly stated or directly implied in the document.
5. For each fact, assign a category: pricing, market_size, pain_point, competitor, technology, regulation, customer_behavior, or general.

## OUTPUT FORMAT
Return a JSON object with three arrays:
{{
  "entities": [
    {{"name": "...", "entity_type": "company|person|product|market|technology|concept", "attributes": {{"key": "value"}}}}
  ],
  "relationships": [
    {{"source": "entity name", "target": "entity name", "type": "relationship_type", "description": "..."}}
  ],
  "facts": [
    {{"content": "The specific fact or statistic", "entities": ["entity name 1", "entity name 2"], "category": "...", "confidence": 0.5-1.0}}
  ]
}}

Return ONLY the JSON object."""

    user_prompt = f"""Extract entities, relationships, and facts from this document:

## Document: {document_name}

{document_text[:8000]}"""

    try:
        response = chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=model,
            temperature=0.3,
            max_tokens=4000,
        )

        extracted = parse_llm_json(
            text=response,
            expected_type=dict,
            context=f"graph extraction from {document_name}",
        )
        return extracted

    except (JSONParseError, LLMRetryExhausted, LLMResponseEmpty) as e:
        logger.error("Failed to extract from document '%s': %s", document_name, str(e)[:200])
        return {"entities": [], "relationships": [], "facts": []}

    except Exception as e:
        logger.error("Unexpected error extracting from '%s': %s", document_name, str(e)[:200])
        return {"entities": [], "relationships": [], "facts": []}


def build_knowledge_graph(
    documents: Dict[str, str],
    product_context: str,
    model: str = "gemini-2.5-flash",
) -> KnowledgeGraph:
    """
    Build a knowledge graph from multiple seed documents.

    Args:
        documents: Dict mapping document names to their text content.
                   e.g., {"company_overview": "...", "market_research": "...", "crm_data": "..."}
        product_context: Description of the product being simulated.
        model: LLM model to use for extraction.

    Returns:
        A populated KnowledgeGraph instance.
    """
    graph = KnowledgeGraph()
    entity_name_to_id: Dict[str, str] = {}

    logger.info("Building knowledge graph from %d documents", len(documents))

    for doc_name, doc_text in documents.items():
        if not doc_text or not doc_text.strip():
            logger.warning("Skipping empty document: %s", doc_name)
            continue

        logger.info("Extracting from document: %s (%d chars)", doc_name, len(doc_text))

        # For long documents, chunk and extract from each chunk
        chunks = _chunk_document(doc_text, max_chunk_size=6000)

        for chunk_idx, chunk in enumerate(chunks):
            chunk_name = f"{doc_name}" if len(chunks) == 1 else f"{doc_name} (part {chunk_idx + 1})"

            extracted = _extract_from_document(chunk, chunk_name, product_context, model)

            # Process entities
            for e_data in extracted.get("entities", []):
                if not isinstance(e_data, dict) or "name" not in e_data:
                    continue
                name = e_data["name"]
                etype = e_data.get("entity_type", "concept")
                eid = _generate_entity_id(name, etype)

                if eid not in graph.entities:
                    entity = Entity(
                        id=eid,
                        name=name,
                        entity_type=etype,
                        attributes=e_data.get("attributes", {}),
                        source_documents=[doc_name],
                    )
                    graph.add_entity(entity)
                    entity_name_to_id[name.lower()] = eid
                else:
                    # Merge attributes from new source
                    existing = graph.entities[eid]
                    existing.attributes.update(e_data.get("attributes", {}))
                    if doc_name not in existing.source_documents:
                        existing.source_documents.append(doc_name)

            # Process relationships
            for r_data in extracted.get("relationships", []):
                if not isinstance(r_data, dict):
                    continue
                source_name = r_data.get("source", "").lower()
                target_name = r_data.get("target", "").lower()

                source_id = entity_name_to_id.get(source_name)
                target_id = entity_name_to_id.get(target_name)

                if source_id and target_id:
                    rel = Relationship(
                        source_id=source_id,
                        target_id=target_id,
                        relationship_type=r_data.get("type", "related_to"),
                        description=r_data.get("description", ""),
                        source_document=doc_name,
                    )
                    graph.add_relationship(rel)

            # Process facts
            for f_data in extracted.get("facts", []):
                if not isinstance(f_data, dict) or "content" not in f_data:
                    continue
                content = f_data["content"]
                fid = _generate_fact_id(content)

                if fid not in graph.facts:
                    # Resolve entity names to IDs
                    entity_ids = []
                    for ename in f_data.get("entities", []):
                        eid = entity_name_to_id.get(ename.lower())
                        if eid:
                            entity_ids.append(eid)

                    fact = Fact(
                        id=fid,
                        content=content,
                        entity_ids=entity_ids,
                        source_document=doc_name,
                        confidence=f_data.get("confidence", 0.8),
                        category=f_data.get("category", "general"),
                    )
                    graph.add_fact(fact)

        logger.info(
            "After '%s': %d entities, %d relationships, %d facts",
            doc_name, len(graph.entities), len(graph.relationships), len(graph.facts),
        )

    logger.info("Knowledge graph complete: %s", graph.stats())
    return graph


def _chunk_document(text: str, max_chunk_size: int = 6000) -> List[str]:
    """Split a document into chunks, preferring paragraph boundaries."""
    if len(text) <= max_chunk_size:
        return [text]

    chunks = []
    paragraphs = text.split("\n\n")
    current_chunk = ""

    for para in paragraphs:
        if len(current_chunk) + len(para) + 2 > max_chunk_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = para
        else:
            current_chunk += "\n\n" + para if current_chunk else para

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks if chunks else [text[:max_chunk_size]]


def build_graph_from_config(config: Dict[str, Any]) -> KnowledgeGraph:
    """
    Build a knowledge graph from simulation config file paths.

    Reads world_model_path, customer_list_path, and transcripts_path
    from the config and builds a unified graph.
    """
    from config import load_context_file

    documents = {}

    # Load available context files
    world_model = load_context_file(config.get("world_model_path"))
    if world_model:
        documents["world_model"] = world_model

    customer_data = load_context_file(config.get("customer_list_path"))
    if customer_data:
        documents["customer_data"] = customer_data

    transcripts = load_context_file(config.get("transcripts_path"))
    if transcripts:
        documents["sales_transcripts"] = transcripts

    # Also include the product description as a document
    product_desc = config.get("product_description", "")
    if product_desc:
        documents["product_description"] = product_desc

    if not documents:
        logger.warning("No documents available for knowledge graph construction")
        return KnowledgeGraph()

    return build_knowledge_graph(
        documents=documents,
        product_context=config.get("product_description", ""),
        model=config.get("llm_model", "gemini-2.5-flash"),
    )
