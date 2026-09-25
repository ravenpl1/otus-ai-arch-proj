"""Domain entities — core business objects independent of any framework.

These are the innermost layer of Clean Architecture.
They have zero dependencies on infrastructure, frameworks, or use cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, List


@dataclass
class Document:
    """Represents a loaded document with metadata."""

    content: str
    source: str  # file path, URL, or identifier
    doc_type: str  # "txt", "md", etc.
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    """A text chunk derived from a Document."""

    id: str
    text: str
    source: str
    chunk_index: int
    security_clearance_level: int = 1
    metadata: dict | None = None


@dataclass
class GuardrailResult:
    """Result of a guardrail safety check."""

    status: str  # "ok", "blocked", "hallucination"
    message: str | None = None


@dataclass
class Company:
    """Represents a legal entity from RFSD dataset."""

    inn: str
    ogrn: str
    short_name: str
    full_name: str
    okved: str
    okved_section: str
    region: str
    age: float | None = None
    creation_date: str | None = None
    dissolution_date: str | None = None
    security_clearance_level: int = 1


@dataclass
class Financials:
    """Financial statements of a company for a given year."""

    id: str  # f"{inn}_{year}"
    inn: str
    year: int
    # Balance sheet
    b_assets: float | None = None
    b_liab: float | None = None
    b_total_equity: float | None = None
    b_fixed_assets: float | None = None
    b_cash_equivalents: float | None = None
    b_shortterm_debt: float | None = None
    b_longterm_debt: float | None = None
    # Profit & Loss
    pl_revenue: float | None = None
    pl_gross_profit: float | None = None
    pl_profit_from_sales: float | None = None
    pl_net_profit: float | None = None
    pl_cost_of_sales: float | None = None
    # Cash Flow
    cf_balance: float | None = None
    cf_balance_operating: float | None = None
    # Flags
    simplified: float | None = None
    outlier: float | None = None


@dataclass
class RetrievalResult:
    """Result of a context retrieval pipeline."""

    query: str
    facts: List[str]
    chunk_ids: List[str]
    user_clearance: int


# ---------------------------------------------------------------------------
# RBAC: role → set of ALLOWED financial fields
# Empty set means ALL fields are allowed.
# ---------------------------------------------------------------------------

_ALL_FINANCIAL_FIELDS: set[str] = {
    "b_assets", "b_liab", "b_total_equity", "b_fixed_assets", "b_cash_equivalents",
    "b_shortterm_debt", "b_longterm_debt",
    "pl_revenue", "pl_gross_profit", "pl_profit_from_sales", "pl_net_profit", "pl_cost_of_sales",
    "cf_balance", "cf_balance_operating",
    "simplified", "outlier",
}

ROLE_ALLOWED_FIELDS: dict[str, set[str]] = {
    "USER": {"pl_revenue"},                     # only revenue
    "FINANCE": _ALL_FINANCIAL_FIELDS,           # all fields
    "DATA_STEWARD": _ALL_FINANCIAL_FIELDS,      # full access to RFSD data
    "ADMIN": _ALL_FINANCIAL_FIELDS,             # all fields
}


def get_restricted_fields(role: str) -> set[str]:
    """Return the set of fields that the given role CANNOT see."""
    allowed = ROLE_ALLOWED_FIELDS.get(role.upper(), {"pl_revenue"})
    return _ALL_FINANCIAL_FIELDS - allowed


def get_allowed_fields(role: str) -> set[str]:
    """Return the set of financial fields that the given role CAN see."""
    return ROLE_ALLOWED_FIELDS.get(role.upper(), {"pl_revenue"})


# Map of financial field names to (cypher expression, human-readable label)
FINANCIAL_FIELD_MAP: dict[str, tuple[str, str]] = {
    "b_assets": ("f.b_assets", "активы"),
    "b_liab": ("f.b_liab", "пассивы"),
    "b_total_equity": ("f.b_total_equity", "собственный капитал"),
    "b_fixed_assets": ("f.b_fixed_assets", "внеоборотные активы"),
    "b_cash_equivalents": ("f.b_cash_equivalents", "денежные средства"),
    "b_shortterm_debt": ("f.b_shortterm_debt", "краткосрочный долг"),
    "b_longterm_debt": ("f.b_longterm_debt", "долгосрочный долг"),
    "pl_revenue": ("f.pl_revenue", "выручка"),
    "pl_gross_profit": ("f.pl_gross_profit", "валовая прибыль"),
    "pl_profit_from_sales": ("f.pl_profit_from_sales", "прибыль от продаж"),
    "pl_net_profit": ("f.pl_net_profit", "чистая прибыль"),
    "pl_cost_of_sales": ("f.pl_cost_of_sales", "себестоимость продаж"),
    "cf_balance": ("f.cf_balance", "денежный поток"),
    "cf_balance_operating": ("f.cf_balance_operating", "денежный поток от операций"),
    "simplified": ("f.simplified", "упрощённая отчётность"),
    "outlier": ("f.outlier", "выброс/аномалия"),
}
