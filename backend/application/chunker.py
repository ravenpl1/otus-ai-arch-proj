"""Text chunker — splits documents into overlapping chunks.

Pure business logic — no infrastructure dependencies.
"""

from __future__ import annotations

from typing import List

from domain.entities import Document, Chunk
from config.settings import CHUNK_SIZE, CHUNK_OVERLAP


def chunk_document(
    doc: Document,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> List[Chunk]:
    """Split a document into overlapping text chunks."""
    text = doc.content
    chunks: List[Chunk] = []
    start = 0
    index = 0

    while start < len(text):
        end = start + chunk_size
        chunk_text = text[start:end]

        if chunk_text.strip():
            chunk_id = f"{doc.source}::chunk_{index}"
            chunks.append(Chunk(
                id=chunk_id,
                text=chunk_text,
                source=doc.source,
                chunk_index=index,
            ))
            index += 1

        start += chunk_size - chunk_overlap

    return chunks


def chunk_documents(
    documents: List[Document],
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> List[Chunk]:
    """Chunk multiple documents."""
    all_chunks: List[Chunk] = []
    for doc in documents:
        all_chunks.extend(chunk_document(doc, chunk_size, chunk_overlap))
    return all_chunks
