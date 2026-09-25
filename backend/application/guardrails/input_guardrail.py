"""Input guardrail — checks user query for safety violations."""

from __future__ import annotations

from domain.entities import GuardrailResult
from domain.ports import InputGuardrailPort
from config.settings import BLOCKED_PHRASES


class InputGuardrail(InputGuardrailPort):
    """Input safety guardrail — blocks queries containing dangerous phrases."""

    def __init__(self, blocked_phrases: tuple[str, ...] | list[str] | None = None) -> None:
        self._blocked_phrases = blocked_phrases or BLOCKED_PHRASES

    def validate(self, query: str) -> GuardrailResult:
        query_lower = query.lower()
        for phrase in self._blocked_phrases:
            if phrase in query_lower:
                return GuardrailResult(status="blocked", message="Доступ заблокирован Control Plane.")
        return GuardrailResult(status="ok", message=None)
