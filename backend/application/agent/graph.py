"""LangGraph agent graph — assembles the StateGraph with all nodes and edges.

Two separate agent graphs:
- FinData Agent: RAG pipeline (Qdrant + Neo4j + LLM)
- Chat Agent: simple LLM conversation (guardrails + LLM)
"""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from application.agent.state import MultiModalAgentState
from application.agent.nodes import (
    extract_input_node,
    input_guardrail_node,
    graph_rag_fetch_node,
    llm_generation_node,
    no_data_response_node,
    output_guardrail_node,
)


def _route_after_guardrail_rag(state: MultiModalAgentState) -> str:
    """FinData Agent: blocked → end, ok → fetch from DB."""
    if state["safety_status"] == "blocked":
        return "end"
    return "fetch"


def _route_after_guardrail_chat(state: MultiModalAgentState) -> str:
    """Chat Agent: blocked → end, ok → generate."""
    if state["safety_status"] == "blocked":
        return "end"
    return "generate"


def _route_after_fetch(state: MultiModalAgentState) -> str:
    """Route after graph_rag_fetch: no data → no_data_response, data → llm."""
    if state.get("data_found"):
        return "generate"
    return "no_data"


def _route_after_output_guardrail(state: MultiModalAgentState) -> str:
    """Route after output guardrail: hallucination → retry, otherwise → end."""
    if state["safety_status"] == "hallucination":
        return "retry"
    return "end"


def build_findata_agent_graph() -> StateGraph:
    """FinData Agent: extract → guardrail → graph_rag_fetch → llm_generation → output_guardrail.

    Full RAG pipeline with Qdrant semantic search and Neo4j financial data.
    """
    workflow = StateGraph(MultiModalAgentState)

    workflow.add_node("extract_input", extract_input_node)
    workflow.add_node("input_guardrail", input_guardrail_node)
    workflow.add_node("graph_rag_fetch", graph_rag_fetch_node)
    workflow.add_node("no_data_response", no_data_response_node)
    workflow.add_node("llm_generation", llm_generation_node)
    workflow.add_node("output_guardrail", output_guardrail_node)

    workflow.set_entry_point("extract_input")
    workflow.add_edge("extract_input", "input_guardrail")

    workflow.add_conditional_edges(
        "input_guardrail",
        _route_after_guardrail_rag,
        {"end": END, "fetch": "graph_rag_fetch"},
    )

    workflow.add_conditional_edges(
        "graph_rag_fetch",
        _route_after_fetch,
        {"generate": "llm_generation", "no_data": "no_data_response"},
    )

    workflow.add_edge("no_data_response", END)
    workflow.add_edge("llm_generation", "output_guardrail")

    workflow.add_conditional_edges(
        "output_guardrail",
        _route_after_output_guardrail,
        {"retry": "graph_rag_fetch", "end": END},
    )

    return workflow.compile()


def build_chat_agent_graph() -> StateGraph:
    """Chat Agent: extract → guardrail → llm_chat → output_guardrail.

    Simple LLM conversation without database retrieval.
    Uses guardrails for safety checks.
    """
    workflow = StateGraph(MultiModalAgentState)

    workflow.add_node("extract_input", extract_input_node)
    workflow.add_node("input_guardrail", input_guardrail_node)
    workflow.add_node("llm_generation", llm_generation_node)
    workflow.add_node("output_guardrail", output_guardrail_node)

    workflow.set_entry_point("extract_input")
    workflow.add_edge("extract_input", "input_guardrail")

    workflow.add_conditional_edges(
        "input_guardrail",
        _route_after_guardrail_chat,
        {"end": END, "generate": "llm_generation"},
    )

    workflow.add_edge("llm_generation", "output_guardrail")

    workflow.add_conditional_edges(
        "output_guardrail",
        _route_after_output_guardrail,
        {"retry": "llm_generation", "end": END},
    )

    return workflow.compile()


# Backward compatibility: default graph is FinData Agent
def build_agent_graph() -> StateGraph:
    """Build the default agent graph (FinData Agent)."""
    return build_findata_agent_graph()
