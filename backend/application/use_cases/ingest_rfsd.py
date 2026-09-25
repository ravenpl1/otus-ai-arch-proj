"""Use Case: Ingest RFSD — loads RFSD CSV into Neo4j (graph) + Qdrant (vectors).

Text descriptions (without numbers) go to Qdrant for semantic search.
Structured financial data goes to Neo4j for graph queries.
"""

from __future__ import annotations

import csv as csv_module
import math
import re
import uuid
from dataclasses import dataclass
from typing import List

from domain.entities import Company, Financials, Chunk
from application.ports import EmbedderPort, VectorStorePort, GraphStorePort


@dataclass
class IngestRFSDOutput:
    """Output DTO from the RFSD ingest use case."""
    companies_indexed: int
    financials_indexed: int
    chunks_indexed: int
    errors: List[str]


def _infer_year(record: dict, default_year: int = 2025) -> int:
    """Infer the financial year from record fields.

    Logic:
    1. If creation_date exists and age exists: year = year_from(creation_date) + int(age)
    2. If only creation_date exists: year = year_from(creation_date)
    3. Otherwise: year = default_year
    """
    creation_date = record.get("creation_date")
    age = record.get("age")

    year_from_date = None
    if creation_date:
        cd = str(creation_date).strip()
        if cd:
            # Try to extract year from various date formats (YYYY, DD.MM.YYYY, YYYY-MM-DD, etc.)
            match = re.search(r"(\d{4})", cd)
            if match:
                year_from_date = int(match.group(1))

    if year_from_date is not None and age is not None:
        age_str = str(age).strip()
        if age_str:
            try:
                age_val = int(float(age_str))
                computed = year_from_date + age_val
                if 1900 <= computed <= 2100:
                    return computed
            except (ValueError, TypeError):
                pass

    if year_from_date is not None and 1900 <= year_from_date <= 2100:
        return year_from_date

    return default_year


def _safe_str(value) -> str:
    """Convert value to string, returning empty string for NaN/None."""
    if value is None:
        return ""
    try:
        if isinstance(value, float) and math.isnan(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _format_company_text(company: Company) -> str:
    """Generate text description of a company WITHOUT financial numbers."""
    parts = [
        f"Компания «{company.short_name}» (полное название: {company.full_name}).",
        f"ИНН: {company.inn}, ОГРН: {company.ogrn}.",
    ]
    if company.region:
        parts.append(f"Зарегистрирована в регионе: {company.region}.")
    parts.append(f"Основной вид деятельности: {company.okved} (секция {company.okved_section}).")
    if company.creation_date:
        parts.append(f"Дата создания: {company.creation_date}.")
    if company.dissolution_date:
        parts.append(f"Компания ликвидирована: {company.dissolution_date}.")
    else:
        parts.append("Компания действующая.")
    return " ".join(parts)


def _process_record(row: dict, row_num: int, default_year: int) -> tuple[Company, Financials, str]:
    """Process a single record dict into Company, Financials, and text description.

    Returns:
        Tuple of (Company, Financials, formatted_text).

    Raises:
        ValueError: If INN is missing.
    """
    inn = _safe_str(row.get("inn"))
    if not inn:
        raise ValueError("INN is empty")

    ogrn = _safe_str(row.get("ogrn"))
    short_name = _safe_str(row.get("short_name")) or _safe_str(row.get("full_name")) or inn
    full_name = _safe_str(row.get("full_name")) or short_name
    okved = _safe_str(row.get("okved"))
    okved_section = _safe_str(row.get("okved_section"))
    region = _safe_str(row.get("region")) or None  # None if empty, so Neo4j won't create property
    age = row.get("age")
    creation_date = _safe_str(row.get("creation_date")) or None
    dissolution_date = _safe_str(row.get("dissolution_date")) or None

    company = Company(
        inn=inn,
        ogrn=ogrn,
        short_name=short_name,
        full_name=full_name,
        okved=okved,
        okved_section=okved_section,
        region=region,
        age=float(age) if age and _safe_str(age) else None,
        creation_date=creation_date,
        dissolution_date=dissolution_date,
    )

    computed_year = _infer_year(row, default_year=default_year)

    financials = Financials(
        id=f"{inn}_{computed_year}",
        inn=inn,
        year=computed_year,
        b_assets=row.get("b_assets"),
        b_liab=row.get("b_liab"),
        b_total_equity=row.get("b_total_equity"),
        b_fixed_assets=row.get("b_fixed_assets"),
        b_cash_equivalents=row.get("b_cash_equivalents"),
        b_shortterm_debt=row.get("b_shortterm_debt"),
        b_longterm_debt=row.get("b_longterm_debt"),
        pl_revenue=row.get("pl_revenue"),
        pl_gross_profit=row.get("pl_gross_profit"),
        pl_profit_from_sales=row.get("pl_profit_from_sales"),
        pl_net_profit=row.get("pl_net_profit"),
        pl_cost_of_sales=row.get("pl_cost_of_sales"),
        cf_balance=row.get("cf_balance"),
        cf_balance_operating=row.get("cf_balance_operating"),
        simplified=row.get("simplified"),
        outlier=row.get("outlier"),
    )

    text = _format_company_text(company)
    return company, financials, text


def execute_ingest_rfsd_batch(
    records: list,
    embedder: EmbedderPort,
    vector_store: VectorStorePort,
    graph_store: GraphStorePort,
    collection: str = "findata",
    year: int = 2025,
) -> IngestRFSDOutput:
    """
    Execute the RFSD ingestion pipeline from a list of record dicts.

    Args:
        records: List of dicts with company/financial data.
        embedder: EmbedderPort for generating embeddings.
        vector_store: VectorStorePort for vector storage (Qdrant).
        graph_store: GraphStorePort for graph storage (Neo4j).
        collection: Target Qdrant collection name.
        year: Default financial year (used when inference is not possible).

    Returns:
        IngestRFSDOutput with counts and errors.
    """
    errors: List[str] = []
    companies_count = 0
    financials_count = 0
    chunks: List[Chunk] = []
    texts: List[str] = []

    for row_num, row in enumerate(records, start=1):
        try:
            # Support both dict and Pydantic model
            if hasattr(row, "model_dump"):
                row = row.model_dump()

            company, financials, text = _process_record(row, row_num, default_year=year)

            # Neo4j: structured data
            graph_store.upsert_company_with_financials(company, financials)
            companies_count += 1
            financials_count += 1

            # Prepare text for Qdrant (without numbers)
            chunk_id = f"company_{company.inn}"
            chunk = Chunk(
                id=chunk_id,
                text=text,
                source="api_batch",
                chunk_index=row_num,
                metadata={"inn": company.inn},
            )
            chunks.append(chunk)
            texts.append(text)

        except ValueError:
            continue  # Skip records without INN
        except Exception as e:
            errors.append(f"Record {row_num}: {e}")

    # Batch embed and upsert to Qdrant (in sub-batches to avoid OOM)
    if chunks:
        SUB_BATCH = 20
        for i in range(0, len(chunks), SUB_BATCH):
            sub_chunks = chunks[i : i + SUB_BATCH]
            sub_texts = texts[i : i + SUB_BATCH]
            try:
                embeddings = embedder.embed_texts(sub_texts)
                vector_store.upsert(sub_chunks, embeddings, collection)
            except Exception as e:
                errors.append(f"Embed/upsert sub-batch {i//SUB_BATCH + 1}: {e}")

        # Link Company -> Chunk in Neo4j
        for chunk in chunks:
            inn = chunk.id.replace("company_", "")
            try:
                graph_store.link_company_to_chunk(inn, chunk.id)
            except Exception as e:
                errors.append(f"Link chunk {chunk.id}: {e}")

    return IngestRFSDOutput(
        companies_indexed=companies_count,
        financials_indexed=financials_count,
        chunks_indexed=len(chunks),
        errors=errors,
    )


def execute_ingest_rfsd(
    csv_path: str,
    embedder: EmbedderPort,
    vector_store: VectorStorePort,
    graph_store: GraphStorePort,
    collection: str = "findata",
    year: int = 2025,
) -> IngestRFSDOutput:
    """
    Execute the RFSD ingestion pipeline from a CSV file.

    Args:
        csv_path: Path to the RFSD CSV file.
        embedder: EmbedderPort for generating embeddings.
        vector_store: VectorStorePort for vector storage (Qdrant).
        graph_store: GraphStorePort for graph storage (Neo4j).
        collection: Target Qdrant collection name.
        year: Default financial year (used when inference is not possible).

    Returns:
        IngestRFSDOutput with counts and errors.
    """
    errors: List[str] = []
    companies_count = 0
    financials_count = 0
    chunks: List[Chunk] = []
    texts: List[str] = []

    # Read CSV — normalize field names to lowercase for _process_record
    _FIELD_MAP = {
        "B_assets": "b_assets",
        "B_liab": "b_liab",
        "B_total_equity": "b_total_equity",
        "B_fixed_assets": "b_fixed_assets",
        "B_cash_equivalents": "b_cash_equivalents",
        "B_shortterm_debt": "b_shortterm_debt",
        "B_longterm_debt": "b_longterm_debt",
        "PL_revenue": "pl_revenue",
        "PL_gross_profit": "pl_gross_profit",
        "PL_profit_from_sales": "pl_profit_from_sales",
        "PL_net_profit": "pl_net_profit",
        "PL_cost_of_sales": "pl_cost_of_sales",
        "CF_balance": "cf_balance",
        "CF_balance_operating": "cf_balance_operating",
    }

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv_module.DictReader(f)
        for row_num, raw_row in enumerate(reader, start=1):
            try:
                # Normalize CSV field names (B_assets → b_assets, etc.)
                row = {}
                for key, value in raw_row.items():
                    normalized_key = _FIELD_MAP.get(key, key)
                    row[normalized_key] = value

                company, financials, text = _process_record(row, row_num, default_year=year)

                # Neo4j: structured data
                graph_store.upsert_company_with_financials(company, financials)
                companies_count += 1
                financials_count += 1

                # Prepare text for Qdrant (without numbers)
                chunk_id = f"company_{company.inn}"
                chunk = Chunk(
                    id=chunk_id,
                    text=text,
                    source=csv_path,
                    chunk_index=row_num,
                    metadata={"inn": company.inn},
                )
                chunks.append(chunk)
                texts.append(text)

            except ValueError:
                continue  # Skip records without INN
            except Exception as e:
                errors.append(f"Row {row_num}: {e}")

    # Batch embed and upsert to Qdrant
    if chunks:
        embeddings = embedder.embed_texts(texts)
        vector_store.upsert(chunks, embeddings, collection)

        # Link Company -> Chunk in Neo4j
        for chunk in chunks:
            inn = chunk.id.replace("company_", "")
            try:
                graph_store.link_company_to_chunk(inn, chunk.id)
            except Exception as e:
                errors.append(f"Link chunk {chunk.id}: {e}")

    return IngestRFSDOutput(
        companies_indexed=companies_count,
        financials_indexed=financials_count,
        chunks_indexed=len(chunks),
        errors=errors,
    )
