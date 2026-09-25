"""Business ports — domain-level interfaces for safety and guardrails.

These ports represent core business rules (security, hallucination detection)
that are fundamental to the domain, not technical infrastructure concerns.

Infrastructure-related ports (LLM, VectorStore, GraphStore, Embedder)
are defined in application/ports.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from domain.entities import GuardrailResult


class InputGuardrailPort(ABC):
    """Abstract interface for input safety validation."""

    @abstractmethod
    def validate(self, query: str) -> GuardrailResult:
        ...


class OutputGuardrailPort(ABC):
    """Abstract interface for output hallucination detection."""

    @abstractmethod
    def validate(self, facts: List[str], response: str) -> GuardrailResult:
        ...
