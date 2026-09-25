"""Placeholder embedder — implements EmbedderPort with dummy vectors."""

from __future__ import annotations

from typing import List

from application.ports import EmbedderPort


class PlaceholderEmbedder(EmbedderPort):
    """Placeholder embedder that returns dummy vectors.

    TODO: Replace with real OllamaEmbeddings-based implementation.
    """

    def __init__(self, vector_size: int = 384) -> None:
        self._vector_size = vector_size

    def embed_text(self, text: str) -> List[float]:
        return [0.0] * self._vector_size

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_text(text) for text in texts]
