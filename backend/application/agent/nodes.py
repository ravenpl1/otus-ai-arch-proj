"""LangGraph agent nodes — thin wrappers that delegate to service modules.

Nodes depend on port interfaces rather than concrete infrastructure.
Dependencies are injected via a shared AgentDependencies container.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from langchain_core.messages import AIMessage

from application.agent.state import MultiModalAgentState
from domain.entities import get_restricted_fields

logger = logging.getLogger(__name__)


class AgentDependencies:
    """Container for agent node dependencies."""

    def __init__(
        self,
        llm_factory,
        vector_store,   # VectorStorePort
        graph_store,    # GraphStorePort
        input_guardrail,   # InputGuardrailPort
        output_guardrail_factory,
        embedder=None,     # EmbedderPort (optional, for GraphRAG)
        qdrant_collection: str = "findata",
    ) -> None:
        self.llm_factory = llm_factory
        self.vector_store = vector_store
        self.graph_store = graph_store
        self.input_guardrail = input_guardrail
        self.output_guardrail_factory = output_guardrail_factory
        self.embedder = embedder
        self.qdrant_collection = qdrant_collection


_deps: AgentDependencies | None = None


def set_dependencies(deps: AgentDependencies) -> None:
    global _deps
    _deps = deps


def _get_deps() -> AgentDependencies:
    if _deps is None:
        raise RuntimeError("Agent dependencies not initialized.")
    return _deps


def extract_input_node(state: MultiModalAgentState) -> dict:
    # Use raw_query from initial state if already provided
    raw_query = state.get("raw_query", "")
    if not raw_query:
        user_msgs = [m for m in state["messages"] if m.type == "human"]
        raw_query = user_msgs[-1].content if user_msgs else ""
    return {
        "raw_query": raw_query,
        "sanitized_query": "",
        "security_scope": {},
        "retrieved_facts": [],
        "llm_response": "",
        "safety_status": "",
        "loop_count": 0,
        "temperature": state.get("temperature", 0.7),
    }


def input_guardrail_node(state: MultiModalAgentState) -> dict:
    deps = _get_deps()
    result = deps.input_guardrail.validate(state["raw_query"])
    if result.status == "blocked":
        return {
            "safety_status": "blocked",
            "llm_response": result.message,
            "messages": [AIMessage(content=result.message)],
        }
    # Compute RBAC restricted fields from user_role
    user_role = state.get("user_role", "USER")
    restricted = get_restricted_fields(user_role)
    return {
        "safety_status": "ok",
        "sanitized_query": state["raw_query"],
        "security_scope": {
            "roles": [user_role],
            "clearance_level": 2,
            "restricted_fields": sorted(restricted),
        },
        "loop_count": 0,
        "retrieved_facts": [],
    }


def graph_rag_fetch_node(state: MultiModalAgentState) -> dict:
    """GraphRAG retrieval: Neo4j (company name search) → Qdrant (text) → Neo4j (financials).

    Pipeline:
    1. Search company by name in Neo4j (exact CONTAINS + fuzzy full-text), limit=1
    2. If found: get text description from Qdrant by INN, financials from Neo4j
    3. Fallback: if Neo4j didn't find — use Qdrant semantic search (embedding)
    """
    deps = _get_deps()
    facts: list[str] = []

    try:
        query_text = state.get("sanitized_query") or state.get("raw_query", "")
        logger.info("graph_rag_fetch_node: query_text=%s", query_text[:200])

        # ---- Step 1: Neo4j — search company by name (exact + fuzzy), limit=1 ----
        t0 = time.monotonic()
        matched_companies = []
        try:
            matched_companies = deps.graph_store.search_companies(query_text, limit=1)
        except Exception as e:
            logger.warning("Neo4j company search failed: %s", e)
        logger.info("Step 1 Neo4j search_companies: %.1fs, found %d", time.monotonic() - t0, len(matched_companies))
        for c in matched_companies:
            logger.info("  Neo4j match: inn=%s, name=%s, score=%s", c.get("inn"), c.get("short_name"), c.get("score"))

        matched_inns: list[str] = []
        text_descriptions: list[str] = []

        if matched_inns_from_neo4j := [c["inn"] for c in matched_companies]:
            matched_inns = matched_inns_from_neo4j[:1]
            logger.info("Neo4j best match: %s (%s)",
                        matched_companies[0]["short_name"], matched_inns[0])

            # ---- Step 2a: Get text description from Qdrant by INN ----
            t1 = time.monotonic()
            try:
                results = deps.vector_store.search_by_payload(
                    collection=deps.qdrant_collection, key="inn", value=matched_inns[0], limit=1
                )
                logger.info("Step 2a Qdrant returned %d results for inn=%s", len(results), matched_inns[0])
                for r in results[:1]:  # Enforce limit=1 as safety measure
                    logger.info("  Qdrant point: id=%s, inn=%s, text=%s",
                                r.get("id"), r.get("payload", {}).get("inn"), r.get("payload", {}).get("text", "")[:80])
                    text = r.get("payload", {}).get("text", "")
                    if text:
                        text_descriptions.append(text)
            except Exception as e:
                logger.warning("Qdrant search_by_payload failed for INN %s: %s", matched_inns[0], e)
            logger.info("Step 2a Qdrant search_by_payload: %.1fs, texts=%d", time.monotonic() - t1, len(text_descriptions))
        else:
            # ---- Step 2b: Fallback — Qdrant semantic search ----
            logger.info("Neo4j found nothing, falling back to Qdrant semantic search")
            t1 = time.monotonic()
            query_vector = deps.embedder.embed_text(query_text) if deps.embedder else []
            if query_vector:
                try:
                    search_results = deps.vector_store.search(
                        query_vector=query_vector, collection=deps.qdrant_collection, limit=3
                    )
                    # Limit to 1 best match
                    if search_results:
                        best = search_results[0]
                        best_inn = best.get("payload", {}).get("inn")
                        if best_inn:
                            matched_inns = [best_inn]
                        text = best.get("payload", {}).get("text", "")
                        if text:
                            text_descriptions = [text]
                except Exception as e:
                    logger.warning("Qdrant semantic search failed: %s", e)
            logger.info("Step 2b Qdrant semantic fallback: %.1fs, texts=%d", time.monotonic() - t1, len(text_descriptions))

        # ---- Step 3: Enrich with financial data from Neo4j (RBAC-filtered) ----
        restricted_fields = state.get("security_scope", {}).get("restricted_fields", [])
        financial_facts: list[str] = []
        if matched_inns:
            t2 = time.monotonic()
            try:
                financial_facts = deps.graph_store.get_financials_by_inns(
                    matched_inns, restricted_fields=restricted_fields, year=None,
                )
                logger.info("Step 3 Neo4j financials: %.1fs, found %d facts for INNs %s",
                            time.monotonic() - t2, len(financial_facts), matched_inns)
            except Exception as e:
                logger.warning("Neo4j financials query failed: %s", e)

        # ---- Step 4: Combine text descriptions + financial facts ----
        facts = text_descriptions + financial_facts

    except Exception as e:
        logger.error("graph_rag_fetch_node unexpected error: %s", e)

    data_found = bool(facts)

    if not facts:
        facts.append("По вашему запросу ничего не найдено. Попробуйте уточнить запрос.")

    return {"retrieved_facts": facts, "loop_count": state["loop_count"] + 1, "data_found": data_found}


def llm_generation_node(state: MultiModalAgentState) -> dict:
    deps = _get_deps()
    llm = deps.llm_factory(state["temperature"])
    system_msg = next((m.content for m in state["messages"] if m.type == "system"), "")
    query = state.get("sanitized_query") or state.get("raw_query", "")
    mode = state.get("mode", "rag")

    logger.info("LLM generation node: mode=%s, query=%s, raw_query=%s, sanitized_query=%s",
                mode, query, state.get("raw_query"), state.get("sanitized_query"))

    if mode == "chat":
        # Chat mode: direct conversation, no retrieval context
        prompt = f"/no_think\n{system_msg}\n\nВопрос: {query}"
    else:
        # RAG mode: include retrieved facts
        context = "\n".join(state.get("retrieved_facts", []))
        prompt = f"/no_think\n{system_msg}\n\nФакты:\n{context}\n\nВопрос: {query}"

    logger.info("LLM prompt (first 2000 chars): %s", prompt[:2000])

    t0 = time.monotonic()
    logger.info("LLM invoke starting...")
    try:
        response = llm.invoke(prompt)
        logger.info("LLM response received in %.1fs, length=%d chars",
                     time.monotonic() - t0, len(response.content))
    except Exception as e:
        logger.error("LLM invoke failed after %.1fs: %s", time.monotonic() - t0, e)
        response = AIMessage(content="Извините, не удалось получить ответ от модели. Попробуйте позже.")
    return {
        "llm_response": response.content,
        "messages": [AIMessage(content=response.content)],
    }


def no_data_response_node(state: MultiModalAgentState) -> dict:
    """Respond directly when no data was found — skip LLM."""
    response = "К сожалению, по вашему запросу информация не найдена в базе данных. Попробуйте уточнить запрос или обратитесь к администратору."
    return {
        "llm_response": response,
        "safety_status": "ok",
        "messages": [AIMessage(content=response)],
    }


def output_guardrail_node(state: MultiModalAgentState) -> dict:
    if state["loop_count"] >= 2:
        return {"safety_status": "ok"}
    deps = _get_deps()
    output_guardrail = deps.output_guardrail_factory()
    result = output_guardrail.validate(state["retrieved_facts"], state["llm_response"])
    return {"safety_status": result.status}
