"""Qdrant adapter — implements VectorStorePort for Qdrant."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Dict, List, Set

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance, Filter, FieldCondition, MatchValue

from domain.entities import Chunk
from application.ports import VectorStorePort

logger = logging.getLogger(__name__)


class QdrantVectorStore(VectorStorePort):
    """Qdrant implementation of VectorStorePort."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client = QdrantClient(url=url)
        self._collections_verified: Set[str] = set()

    def search(self, query_vector: List[float], collection: str, limit: int = 5) -> List[dict]:
        results = self._client.query_points(
            collection_name=collection,
            query=query_vector,
            limit=limit,
        ).points
        return [
            {"id": r.id, "score": r.score, "payload": r.payload or {}}
            for r in results
        ]

    def search_with_filter(
        self,
        query_vector: List[float],
        collection: str,
        filters: Dict[str, str],
        limit: int = 10,
    ) -> List[dict]:
        """Semantic search with payload filters (region, okved_section, etc.)."""
        conditions = [
            FieldCondition(key=k, match=MatchValue(value=v))
            for k, v in filters.items()
        ]
        query_filter = Filter(must=conditions)
        results = self._client.query_points(
            collection_name=collection,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
        ).points
        return [
            {"id": r.id, "score": r.score, "payload": r.payload or {}}
            for r in results
        ]

    def search_by_payload(self, collection: str, key: str, value: str, limit: int = 5) -> List[dict]:
        """Search by exact payload field match (e.g. inn)."""
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        payload_filter = Filter(
            must=[FieldCondition(key=key, match=MatchValue(value=value))]
        )

        results = self._client.scroll(
            collection_name=collection,
            scroll_filter=payload_filter,
            limit=limit,
        )[0]

        return [
            {"id": str(r.id), "score": 1.0, "payload": r.payload or {}}
            for r in results
        ]

    def _reconnect(self) -> None:
        """Recreate Qdrant client after connection loss."""
        logger.warning("Qdrant reconnecting to %s", self._url)
        self._client = QdrantClient(url=self._url)

    def upsert(self, chunks: List[Chunk], embeddings: List[List[float]], collection: str) -> None:
        self.ensure_collection(collection, vector_size=len(embeddings[0]))
        points = [
            PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.id)),
                vector=embedding,
                payload={"id": chunk.id, "text": chunk.text, "source": chunk.source, **(chunk.metadata or {})},
            )
            for chunk, embedding in zip(chunks, embeddings)
        ]
        for attempt in range(3):
            try:
                self._client.upsert(collection_name=collection, points=points)
                return
            except Exception as e:
                logger.warning("Qdrant upsert attempt %d/3 failed: %s", attempt + 1, e)
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    self._reconnect()
                else:
                    raise

    def ensure_collection(self, collection: str, vector_size: int = 384) -> None:
        if collection in self._collections_verified:
            return
        try:
            collections = [c.name for c in self._client.get_collections().collections]
        except Exception as e:
            logger.warning("Qdrant get_collections failed, reconnecting: %s", e)
            self._reconnect()
            collections = [c.name for c in self._client.get_collections().collections]
        if collection not in collections:
            self._client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
        self._collections_verified.add(collection)

    def check_connectivity(self) -> None:
        self._client.get_collections()
