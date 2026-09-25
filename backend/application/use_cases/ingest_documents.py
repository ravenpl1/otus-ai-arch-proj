"""Use Case: Ingest Documents — orchestrates document loading, chunking, and indexing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from domain.entities import Document, Chunk
from application.ports import EmbedderPort, VectorStorePort, GraphStorePort
from application.chunker import chunk_documents


@dataclass
class IngestInput:
    """Input DTO for the ingest documents use case."""
    file_paths: List[str]
    file_names: List[str]


@dataclass
class IngestOutput:
    """Output DTO from the ingest documents use case."""
    chunks_indexed: int
    vector_collection: str
    graph_nodes_created: int


def execute_ingest_documents(
    ingest_input: IngestInput,
    documents: List[Document],
    embedder: EmbedderPort,
    vector_store: VectorStorePort,
    graph_store: GraphStorePort,
    collection: str = "documents",
) -> IngestOutput:
    """
    Execute the document ingestion pipeline.

    Args:
        ingest_input: IngestInput DTO.
        documents: Pre-loaded documents.
        embedder: EmbedderPort for generating embeddings.
        vector_store: VectorStorePort for vector storage.
        graph_store: GraphStorePort for graph storage.
        collection: Target collection name.

    Returns:
        IngestOutput DTO with indexing counts.
    """
    chunks: List[Chunk] = chunk_documents(documents)

    texts = [chunk.text for chunk in chunks]
    embeddings = embedder.embed_texts(texts)

    vector_store.upsert(chunks, embeddings, collection)
    graph_store.index_chunks(chunks)

    return IngestOutput(
        chunks_indexed=len(chunks),
        vector_collection=collection,
        graph_nodes_created=len(chunks),
    )
