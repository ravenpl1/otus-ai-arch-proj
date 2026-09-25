"""Agent state — LangGraph-specific state schema."""

from __future__ import annotations

from typing import Annotated, TypedDict, List, Dict, Any

from langgraph.graph.message import add_messages


class MultiModalAgentState(TypedDict):
    """State schema for the LangGraph RAG agent."""

    messages: Annotated[list, add_messages]
    raw_query: str
    sanitized_query: str
    security_scope: Dict[str, Any]
    retrieved_facts: List[str]
    llm_response: str
    safety_status: str
    loop_count: int
    temperature: float
    user_role: str
    mode: str  # "rag" (default) or "chat"
    data_found: bool  # True if graph_rag_fetch found actual data
