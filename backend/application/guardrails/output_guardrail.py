"""Output guardrail — LLM-as-a-Judge hallucination detection."""

from __future__ import annotations

from typing import List

from domain.entities import GuardrailResult
from domain.ports import OutputGuardrailPort
from application.ports import LLMPort


class OutputGuardrail(OutputGuardrailPort):
    """Output hallucination guardrail — uses LLM-as-a-Judge pattern."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    def validate(self, facts: List[str], response: str) -> GuardrailResult:
        judge_prompt = (
            f"Факты: {facts}\n"
            f"Ответ: {response}\n"
            f"Содержит галлюцинации? Ответь ДА или НЕТ:"
        )
        judge_result = self._llm.invoke(judge_prompt).content.strip().upper()
        if "ДА" in judge_result:
            return GuardrailResult(status="hallucination", message="Ответ содержит галлюцинации, повторная генерация.")
        return GuardrailResult(status="ok", message=None)
