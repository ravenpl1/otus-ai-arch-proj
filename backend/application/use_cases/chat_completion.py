"""Use Case: Chat Completion — orchestrates the RAG agent pipeline.

This is the Application layer in Clean Architecture.
It depends only on domain entities and port interfaces,
with zero knowledge of FastAPI, HTTP, or any framework.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import List

import logging

from langchain_core.messages import SystemMessage, HumanMessage

from config.settings import SYSTEM_PROMPT, SYSTEM_PROMPT_CHAT, LLM_TEMPERATURE_GENERATION

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    """A single message in the conversation."""
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class ChatCompletionInput:
    """Input DTO for the chat completion use case."""
    messages: List[ChatMessage]
    model: str = "findata-agent"
    temperature: float = LLM_TEMPERATURE_GENERATION
    user_role: str = "USER"


@dataclass
class ChatCompletionOutput:
    """Output DTO from the chat completion use case."""
    id: str
    model: str
    content: str
    created: int = field(default_factory=lambda: int(time.time()))
    object: str = "chat.completion"
    finish_reason: str = "stop"


def execute_chat_completion(
    agent,
    request: ChatCompletionInput,
) -> ChatCompletionOutput:
    """
    Execute the chat completion pipeline.

    Args:
        agent: Compiled LangGraph agent (from bootstrap).
        request: ChatCompletionInput DTO.

    Returns:
        ChatCompletionOutput DTO.
    """
    # Map model name to agent mode
    mode = "chat" if request.model == "chat-agent" else "rag"
    system_prompt = SYSTEM_PROMPT_CHAT if mode == "chat" else SYSTEM_PROMPT

    # Extract last user message as the query
    # Treat any non-system/non-assistant message as user input
    user_query = ""
    messages_lc = [SystemMessage(content=system_prompt)]
    for m in request.messages:
        role_lower = m.role.lower().strip()
        logger.info("ChatCompletion: message role=%s, content=%s", m.role, m.content[:50])
        if role_lower not in ("system", "assistant"):
            messages_lc.append(HumanMessage(content=m.content))
            user_query = m.content  # keep the last user message

    inputs = {
        "messages": messages_lc,
        "raw_query": user_query,
        "sanitized_query": "",
        "security_scope": {},
        "retrieved_facts": [],
        "llm_response": "",
        "safety_status": "",
        "loop_count": 0,
        "temperature": request.temperature,
        "user_role": request.user_role,
        "mode": mode,
        "data_found": False,
    }
    logger.info("ChatCompletion: mode=%s, user_query=%s, messages=%d", mode, user_query, len(messages_lc))

    output = agent.invoke(inputs)
    answer = output["messages"][-1].content

    return ChatCompletionOutput(
        id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
        model=request.model,
        content=answer,
    )
