"""GuardrailPipeline — reusable composite guardrail combining input + output checks."""

from __future__ import annotations

from typing import List

from domain.entities import GuardrailResult
from domain.ports import InputGuardrailPort, OutputGuardrailPort


class GuardrailPipeline:
    """Orchestrates InputGuardrail and OutputGuardrail through their port interfaces."""

    def __init__(
        self,
        input_guardrail: InputGuardrailPort,
        output_guardrail: OutputGuardrailPort,
    ) -> None:
        self._input_guardrail = input_guardrail
        self._output_guardrail = output_guardrail

    def validate_input(self, query: str) -> GuardrailResult:
        return self._input_guardrail.validate(query)

    def validate_output(self, facts: List[str], response: str) -> GuardrailResult:
        return self._output_guardrail.validate(facts, response)
