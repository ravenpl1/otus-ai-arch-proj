"""Infrastructure ports — technical interfaces for external systems.

These ports are used by the application layer (use cases, agent)
to interact with infrastructure (LLMs, vector stores, graph stores, embedders).
They are defined here (in application) rather than in domain because they
represent technical capabilities, not core business rules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Protocol

from domain.entities import Chunk, Company, Financials


class LLMPort(Protocol):
    """Abstract interface for Large Language Model interactions."""

    def invoke(self, prompt: str) -> str:
        """Send a prompt to the LLM and return the response text."""
        ...


class VectorStorePort(ABC):
    """Abstract interface for vector storage operations."""

    @abstractmethod
    def search(self, query_vector: List[float], collection: str, limit: int) -> List[dict]:
        ...

    @abstractmethod
    def search_with_filter(
        self,
        query_vector: List[float],
        collection: str,
        filters: Dict[str, str],
        limit: int = 10,
    ) -> List[dict]:
        """Semantic search with payload filters (region, okved_section, etc.)."""
        ...

    @abstractmethod
    def search_by_payload(self, collection: str, key: str, value: str, limit: int = 5) -> List[dict]:
        """Search by exact payload field match (e.g. inn)."""
        ...

    @abstractmethod
    def upsert(self, chunks: List[Chunk], embeddings: List[List[float]], collection: str) -> None:
        ...

    @abstractmethod
    def ensure_collection(self, collection: str, vector_size: int) -> None:
        ...


class GraphStorePort(ABC):
    """Abstract interface for graph database operations."""

    @abstractmethod
    def filter_chunks_by_clearance(self, chunk_ids: List[str], clearance: int) -> List[str]:
        ...

    @abstractmethod
    def index_chunks(self, chunks: List[Chunk], default_clearance: int = 1) -> None:
        ...

    @abstractmethod
    def ensure_constraints(self) -> None:
        ...

    @abstractmethod
    def check_connectivity(self) -> None:
        ...

    @abstractmethod
    def init_schema(self) -> None:
        """Create constraints, indexes, and seed reference data (IndustrySection, Region)."""
        ...

    @abstractmethod
    def upsert_company_with_financials(self, company: Company, fin: Financials) -> None:
        """Upsert a Company node with its Financials, Region, and IndustrySection links."""
        ...

    @abstractmethod
    def link_company_to_chunk(self, inn: str, chunk_id: str) -> None:
        """Create HAS_CHUNK relationship between Company and Chunk."""
        ...

    @abstractmethod
    def search_companies(
        self,
        query: str,
        limit: int = 5,
    ) -> List[Dict]:
        """Search companies by name using exact + fuzzy matching.

        Tries exact CONTAINS first, then falls back to full-text fuzzy search.

        Args:
            query: Company name (or part of it) to search for.
            limit: Maximum number of results.

        Returns:
            List of dicts with keys: inn, short_name, full_name, region, okved, score.
        """
        ...

    @abstractmethod
    def get_financials_by_inns(
        self,
        inns: List[str],
        filters: Optional[Dict] = None,
        restricted_fields: Optional[List[str]] = None,
        year: Optional[int] = None,
    ) -> List[str]:
        """Retrieve financial facts for companies by INN list.

        Args:
            inns: List of company INNs.
            filters: Optional Cypher WHERE clauses.
            restricted_fields: Fields the user is NOT allowed to see (RBAC).
            year: Optional year filter. If None, returns all years.
        """
        ...


class EmbedderPort(ABC):
    """Abstract interface for text embedding generation."""

    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        ...

    @abstractmethod
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        ...
