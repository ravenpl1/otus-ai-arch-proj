"""Neo4j adapter — implements GraphStorePort for Neo4j.

Handles the RFSD knowledge graph: Company, Financials, Region, IndustrySection, Chunk.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from neo4j import GraphDatabase, Driver

logger = logging.getLogger(__name__)

from domain.entities import Chunk, Company, Financials, FINANCIAL_FIELD_MAP
from application.ports import GraphStorePort


# OKVED sections A-U (seed reference data)
INDUSTRY_SECTIONS: List[Dict[str, str]] = [
    {"code": "A", "name": "Сельское, лесное хозяйство, охота, рыболовство и рыбоводство"},
    {"code": "B", "name": "Добыча полезных ископаемых"},
    {"code": "C", "name": "Обрабатывающие производства"},
    {"code": "D", "name": "Обеспечение электрической энергией, газом и паром"},
    {"code": "E", "name": "Водоснабжение; водоотведение, организация сбора и утилизации отходов"},
    {"code": "F", "name": "Строительство"},
    {"code": "G", "name": "Торговля оптовая и розничная; ремонт автотранспортных средств и мотоциклов"},
    {"code": "H", "name": "Транспортировка и хранение"},
    {"code": "I", "name": "Деятельность гостиниц и предприятий общественного питания"},
    {"code": "J", "name": "Деятельность в области информации и связи"},
    {"code": "K", "name": "Деятельность финансовая и страховая"},
    {"code": "L", "name": "Деятельность по операциям с недвижимым имуществом"},
    {"code": "M", "name": "Деятельность профессиональная, научная и техническая"},
    {"code": "N", "name": "Деятельность административная и сопутствующие дополнительные услуги"},
    {"code": "O", "name": "Государственное управление и обеспечение военной безопасности; социальное обеспечение"},
    {"code": "P", "name": "Образование"},
    {"code": "Q", "name": "Деятельность в области здравоохранения и социальных услуг"},
    {"code": "R", "name": "Деятельность в области культуры, спорта, организации досуга и развлечений"},
    {"code": "S", "name": "Предоставление прочих видов услуг"},
    {"code": "T", "name": "Деятельность домашних хозяйств как работодателей"},
    {"code": "U", "name": "Деятельность экстерриториальных организаций и органов"},
]


def _safe_float(value) -> Optional[float]:
    """Convert a value to float, returning None for NaN/None/invalid."""
    if value is None:
        return None
    try:
        import math
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return None


class Neo4jGraphStore(GraphStorePort):
    """Neo4j implementation of GraphStorePort with RFSD knowledge graph."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        self._driver: Driver = GraphDatabase.driver(
            uri, auth=(user, password),
            notifications_min_severity="WARNING",
        )

    # ------------------------------------------------------------------
    # Schema initialization
    # ------------------------------------------------------------------

    def init_schema(self) -> None:
        """Create constraints, indexes, and seed IndustrySection reference data."""
        statements = [
            "CREATE CONSTRAINT company_inn_unique IF NOT EXISTS FOR (c:Company) REQUIRE c.inn IS UNIQUE",
            "CREATE CONSTRAINT region_name_unique IF NOT EXISTS FOR (r:Region) REQUIRE r.name IS UNIQUE",
            "CREATE CONSTRAINT industry_code_unique IF NOT EXISTS FOR (i:IndustrySection) REQUIRE i.code IS UNIQUE",
            "CREATE CONSTRAINT financials_id_unique IF NOT EXISTS FOR (f:Financials) REQUIRE f.id IS UNIQUE",
            "CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS FOR (ch:Chunk) REQUIRE ch.id IS UNIQUE",
            "CREATE INDEX company_okved IF NOT EXISTS FOR (c:Company) ON (c.okved)",
            "CREATE INDEX company_region IF NOT EXISTS FOR (c:Company) ON (c.region)",
            "CREATE INDEX company_okved_section IF NOT EXISTS FOR (c:Company) ON (c.okved_section)",
            "CREATE FULLTEXT INDEX company_name_ft IF NOT EXISTS FOR (c:Company) ON EACH [c.short_name, c.full_name]",
        ]

        with self._driver.session() as session:
            for stmt in statements:
                session.run(stmt)
            session.run(
                "UNWIND $sections AS s "
                "MERGE (i:IndustrySection {code: s.code}) "
                "SET i.name = s.name",
                sections=INDUSTRY_SECTIONS,
            )

    # ------------------------------------------------------------------
    # Company + Financials upsert
    # ------------------------------------------------------------------

    def upsert_company_with_financials(self, company: Company, fin: Financials) -> None:
        """Upsert Company node with Region, IndustrySection, and Financials links."""
        cypher_core = """
            MERGE (c:Company {inn: $inn})
            SET c.ogrn              = $ogrn,
                c.short_name        = $short_name,
                c.full_name         = $full_name,
                c.okved             = $okved,
                c.okved_section     = $okved_section,
                c.age               = $age,
                c.creation_date     = $creation_date,
                c.dissolution_date  = $dissolution_date,
                c.security_clearance_level = $clearance

            MERGE (i:IndustrySection {code: $okved_section})
            MERGE (c)-[:CLASSIFIED_AS]->(i)

            MERGE (f:Financials {id: $fin_id})
            SET f.inn                = $fin_inn,
                f.year               = $year,
                f.b_assets           = $b_assets,
                f.b_liab             = $b_liab,
                f.b_total_equity     = $b_total_equity,
                f.b_fixed_assets     = $b_fixed_assets,
                f.b_cash_equivalents = $b_cash_equivalents,
                f.b_shortterm_debt   = $b_shortterm_debt,
                f.b_longterm_debt    = $b_longterm_debt,
                f.pl_revenue         = $pl_revenue,
                f.pl_gross_profit    = $pl_gross_profit,
                f.pl_profit_from_sales = $pl_profit_from_sales,
                f.pl_net_profit      = $pl_net_profit,
                f.pl_cost_of_sales   = $pl_cost_of_sales,
                f.cf_balance         = $cf_balance,
                f.cf_balance_operating = $cf_balance_operating,
                f.simplified         = $simplified,
                f.outlier            = $outlier
            MERGE (c)-[:HAS_FINANCIALS]->(f)
        """

        cypher_region = """
            MATCH (c:Company {inn: $inn})
            MERGE (r:Region {name: $region})
            MERGE (c)-[:BELONGS_TO]->(r)
        """

        params = {
            "inn": company.inn,
            "ogrn": company.ogrn,
            "short_name": company.short_name,
            "full_name": company.full_name,
            "okved": company.okved,
            "okved_section": company.okved_section,
            "age": _safe_float(company.age),
            "creation_date": company.creation_date,
            "dissolution_date": company.dissolution_date,
            "clearance": company.security_clearance_level,
            "fin_id": fin.id,
            "fin_inn": fin.inn,
            "year": fin.year,
            "b_assets": _safe_float(fin.b_assets),
            "b_liab": _safe_float(fin.b_liab),
            "b_total_equity": _safe_float(fin.b_total_equity),
            "b_fixed_assets": _safe_float(fin.b_fixed_assets),
            "b_cash_equivalents": _safe_float(fin.b_cash_equivalents),
            "b_shortterm_debt": _safe_float(fin.b_shortterm_debt),
            "b_longterm_debt": _safe_float(fin.b_longterm_debt),
            "pl_revenue": _safe_float(fin.pl_revenue),
            "pl_gross_profit": _safe_float(fin.pl_gross_profit),
            "pl_profit_from_sales": _safe_float(fin.pl_profit_from_sales),
            "pl_net_profit": _safe_float(fin.pl_net_profit),
            "pl_cost_of_sales": _safe_float(fin.pl_cost_of_sales),
            "cf_balance": _safe_float(fin.cf_balance),
            "cf_balance_operating": _safe_float(fin.cf_balance_operating),
            "simplified": _safe_float(fin.simplified),
            "outlier": _safe_float(fin.outlier),
        }

        with self._driver.session() as session:
            session.run(cypher_core, **params)
            if company.region:
                session.run(cypher_region, inn=company.inn, region=company.region)

    # ------------------------------------------------------------------
    # Link Company to Chunk
    # ------------------------------------------------------------------

    def link_company_to_chunk(self, inn: str, chunk_id: str) -> None:
        """Create HAS_CHUNK relationship between Company and Chunk."""
        cypher = """
            MATCH (c:Company {inn: $inn})
            MATCH (ch:Chunk {id: $chunk_id})
            MERGE (c)-[:HAS_CHUNK]->(ch)
        """
        with self._driver.session() as session:
            session.run(cypher, inn=inn, chunk_id=chunk_id)

    # ------------------------------------------------------------------
    # Query: financial facts by INN list
    # ------------------------------------------------------------------

    def get_financials_by_inns(
        self,
        inns: List[str],
        filters: Optional[Dict] = None,
        restricted_fields: Optional[List[str]] = None,
        year: Optional[int] = None,
    ) -> List[str]:
        """Retrieve human-readable financial facts for companies by INN list.

        RBAC is enforced at the Cypher level — only allowed fields are RETURNed
        from Neo4j, so restricted data never leaves the database.

        Args:
            inns: List of company INNs (from Qdrant search results).
            filters: Optional Cypher WHERE clauses.
            restricted_fields: Fields the user is NOT allowed to see (RBAC).
            year: Optional year filter. If None, returns all years.

        Returns:
            List of fact strings for LLM context, with restricted fields excluded.
        """
        if not inns:
            return ["Компании не найдены."]

        restricted = set(restricted_fields or [])

        # Build dynamic RETURN clause — only allowed financial fields
        fin_return_parts = []
        for field_name, (cypher_expr, _label) in FINANCIAL_FIELD_MAP.items():
            if field_name not in restricted:
                alias = field_name
                fin_return_parts.append(f"{cypher_expr} AS {alias}")

        fin_return = ",\n                   ".join(fin_return_parts)
        if fin_return:
            fin_return = ",\n                   " + fin_return

        where_extra = ""
        if filters:
            conditions = []
            for fld, op_value in filters.items():
                conditions.append(f"f.{fld} {op_value}")
            if conditions:
                where_extra = "AND " + " AND ".join(conditions)

        year_filter = ""
        if year is not None:
            year_filter = "AND f.year = $year"

        cypher = f"""
            MATCH (c:Company)-[:HAS_FINANCIALS]->(f:Financials)
            WHERE c.inn IN $inns {year_filter} {where_extra}
            RETURN c.inn AS inn,
                   c.short_name AS name,
                   c.region AS region,
                   c.okved_section AS section,
                   f.year AS year
                   {fin_return}
            ORDER BY c.short_name, f.year
        """

        facts: List[str] = []
        with self._driver.session() as session:
            params: dict = {"inns": inns}
            if year is not None:
                params["year"] = year
            result = session.run(cypher, **params)
            for record in result:
                name = record["name"] or "-"
                inn = record["inn"]
                region = record["region"] or "-"
                rec_year = record["year"]

                parts = [f"Компания «{name}» (ИНН: {inn}, регион: {region})"]
                if rec_year:
                    parts.append(f"за {rec_year} год:")

                # Iterate only over allowed fields (those returned by Neo4j)
                for field_name, (_cypher_expr, label) in FINANCIAL_FIELD_MAP.items():
                    if field_name in restricted:
                        continue
                    value = record.get(field_name)
                    if value is None:
                        continue
                    # Format numeric values with thousand separator
                    if field_name in ("simplified", "outlier"):
                        if value and value > 0:
                            tag = "упрощённая отчётность" if field_name == "simplified" else "выброс/аномалия"
                            parts.append(f"[{tag}]")
                    else:
                        try:
                            parts.append(f"{label}={float(value):,.0f}")
                        except (ValueError, TypeError):
                            parts.append(f"{label}={value}")

                facts.append(" ".join(parts))

        if not facts:
            facts.append("Финансовые данные по запрошенным компаниям не найдены.")
        return facts

    # ------------------------------------------------------------------
    # Company search (exact + fuzzy)
    # ------------------------------------------------------------------

    def search_companies(
        self,
        query: str,
        limit: int = 5,
    ) -> List[Dict]:
        """Search companies by name: exact CONTAINS first, then fuzzy full-text."""
        # Step 1: Exact match (CONTAINS)
        exact_cypher = """
            MATCH (c:Company)
            WHERE c.short_name CONTAINS $query OR c.full_name CONTAINS $query
            RETURN c.inn AS inn,
                   c.short_name AS short_name,
                   c.full_name AS full_name,
                   c.region AS region,
                   c.okved AS okved,
                   1.0 AS score
            LIMIT $limit
        """

        with self._driver.session() as session:
            result = session.run(exact_cypher, query=query, limit=limit)
            companies = [
                {
                    "inn": r["inn"],
                    "short_name": r["short_name"],
                    "full_name": r["full_name"],
                    "region": r["region"],
                    "okved": r["okved"],
                    "score": r["score"],
                }
                for r in result
            ]

        if companies:
            return companies

        # Step 2: Fuzzy full-text search (Levenshtein distance ~2)
        fuzzy_query = f"{query}~2"
        fuzzy_cypher = """
            CALL db.index.fulltext.queryNodes("company_name_ft", $fuzzy_query)
            YIELD node, score
            RETURN node.inn AS inn,
                   node.short_name AS short_name,
                   node.full_name AS full_name,
                   node.region AS region,
                   node.okved AS okved,
                   score AS score
            ORDER BY score DESC
            LIMIT $limit
        """

        try:
            with self._driver.session() as session:
                result = session.run(fuzzy_cypher, fuzzy_query=fuzzy_query, limit=limit)
                companies = [
                    {
                        "inn": r["inn"],
                        "short_name": r["short_name"],
                        "full_name": r["full_name"],
                        "region": r["region"],
                        "okved": r["okved"],
                        "score": r["score"],
                    }
                    for r in result
                ]
            return companies
        except Exception as e:
            logger.warning("Neo4j fuzzy search failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # Legacy methods (from original implementation)
    # ------------------------------------------------------------------

    def filter_chunks_by_clearance(self, chunk_ids: List[str], clearance: int) -> List[str]:
        cypher_query = """
        MATCH (c:Chunk)
        WHERE c.id IN $ids AND c.security_clearance_level <= $clearance
        RETURN c.text_content AS text
        """
        facts: List[str] = []
        with self._driver.session() as session:
            result = session.run(cypher_query, ids=chunk_ids, clearance=clearance)
            for record in result:
                facts.append(record["text"])
        if not facts:
            facts.append("Контекст не найден или доступ ограничен.")
        return facts

    def index_chunks(self, chunks: List[Chunk], default_clearance: int = 1) -> None:
        cypher = """
        UNWIND $chunks AS ch
        MERGE (c:Chunk {id: ch.id})
        SET c.text_content = ch.text,
            c.source = ch.source,
            c.chunk_index = ch.chunk_index,
            c.security_clearance_level = ch.clearance
        """
        data = [
            {
                "id": chunk.id, "text": chunk.text, "source": chunk.source,
                "chunk_index": chunk.chunk_index,
                "clearance": chunk.security_clearance_level or default_clearance,
            }
            for chunk in chunks
        ]
        with self._driver.session() as session:
            session.run(cypher, chunks=data)

    def ensure_constraints(self) -> None:
        with self._driver.session() as session:
            session.run(
                "CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS "
                "FOR (c:Chunk) REQUIRE c.id IS UNIQUE"
            )

    def check_connectivity(self) -> None:
        with self._driver.session() as session:
            session.run("RETURN 1")

    def close(self) -> None:
        self._driver.close()
