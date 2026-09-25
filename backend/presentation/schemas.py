"""API schemas — Pydantic models for HTTP request/response serialization."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from config.settings import LLM_TEMPERATURE_GENERATION


class ChatMessageSchema(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = Field(
        default="findata-agent",
        description="Agent: 'findata-agent' (GraphRAG with Qdrant+Neo4j) or 'chat-agent' (simple LLM)",
        pattern="^(findata-agent|chat-agent)$",
    )
    messages: List[ChatMessageSchema]
    temperature: float = Field(default=LLM_TEMPERATURE_GENERATION, ge=0.0, le=2.0)
    user_role: str = Field(default="USER", description="User role: USER, FINANCE, or ADMIN")


class ChatChoiceMessage(BaseModel):
    role: str = "assistant"
    content: str


class ChatChoice(BaseModel):
    index: int = 0
    message: ChatChoiceMessage
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatChoice]


class IngestResponse(BaseModel):
    chunks_indexed: int
    vector_collection: str
    graph_nodes_created: int


class HealthResponse(BaseModel):
    status: str = "ok"


class IngestRFSDRecordRequest(BaseModel):
    """Single RFSD company record for batch ingestion."""
    inn: str = Field(..., description="ИНН компании")
    ogrn: str = Field(default="", description="ОГРН компании")
    short_name: str = Field(default="", description="Краткое наименование")
    full_name: str = Field(default="", description="Полное наименование")
    okved: str = Field(default="", description="Основной вид деятельности")
    okved_section: str = Field(default="", description="Секция ОКВЭД")
    region: str = Field(default="", description="Регион регистрации")
    age: float | None = Field(default=None, description="Возраст компании")
    creation_date: str | None = Field(default=None, description="Дата создания")
    dissolution_date: str | None = Field(default=None, description="Дата ликвидации")
    # Financial fields
    b_assets: float | None = Field(default=None)
    b_liab: float | None = Field(default=None)
    b_total_equity: float | None = Field(default=None)
    b_fixed_assets: float | None = Field(default=None)
    b_cash_equivalents: float | None = Field(default=None)
    b_shortterm_debt: float | None = Field(default=None)
    b_longterm_debt: float | None = Field(default=None)
    pl_revenue: float | None = Field(default=None)
    pl_gross_profit: float | None = Field(default=None)
    pl_profit_from_sales: float | None = Field(default=None)
    pl_net_profit: float | None = Field(default=None)
    pl_cost_of_sales: float | None = Field(default=None)
    cf_balance: float | None = Field(default=None)
    cf_balance_operating: float | None = Field(default=None)
    simplified: float | None = Field(default=None)
    outlier: float | None = Field(default=None)


class IngestRFSDBatchRequest(BaseModel):
    """Batch of RFSD company records for ingestion."""
    records: List[IngestRFSDRecordRequest] = Field(..., description="Список записей компаний")
    year: int = Field(default=2025, description="Финансовый год по умолчанию (если не удаётся вычислить из данных)")


class IngestRFSDBatchResponse(BaseModel):
    """Response from batch RFSD ingestion."""
    companies_indexed: int
    financials_indexed: int
    chunks_indexed: int
    errors: List[str] = Field(default_factory=list)
