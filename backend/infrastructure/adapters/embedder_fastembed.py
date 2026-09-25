"""FastEmbed-based embedder — implements EmbedderPort with real embeddings."""

from __future__ import annotations

import logging
from typing import List

from fastembed import TextEmbedding
from fastembed.common.model_description import PoolingType, ModelSource

from application.ports import EmbedderPort

logger = logging.getLogger(__name__)

# Register intfloat/multilingual-e5-small as a custom model in FastEmbed
# (not built-in, so we register it before first use)
try:
    TextEmbedding.add_custom_model(
        model="intfloat/multilingual-e5-small",
        pooling=PoolingType.MEAN,
        normalization=True,
        sources=ModelSource(hf="intfloat/multilingual-e5-small"),
        dim=384,
        model_file="onnx/model.onnx",
    )
    logger.info("FastEmbed: registered custom model intfloat/multilingual-e5-small")
except Exception as e:
    # Already registered or import issue — ignore
    logger.debug("FastEmbed: custom model registration: %s", e)


class FastEmbedEmbedder(EmbedderPort):
    """Embedder using FastEmbed with intfloat/multilingual-e5-small.

    Downloads the model from Hugging Face on first use.
    Vector size: 384 dimensions.
    """

    def __init__(self, model_name: str = "intfloat/multilingual-e5-small") -> None:
        logger.info("FastEmbed: loading model '%s'...", model_name)
        self._model = TextEmbedding(model_name=model_name)
        self._model_name = model_name
        # Get vector size from a test embedding
        test = list(self._model.embed(["test"]))[0]
        self._vector_size = len(test)
        logger.info("FastEmbed: model loaded, vector_size=%d", self._vector_size)

    def embed_text(self, text: str) -> List[float]:
        """Embed a single text. Returns list of floats."""
        # multilingual-e5 uses "query: " prefix for search queries
        if "e5" in self._model_name and not text.startswith("query:"):
            text = f"query: {text}"
        result = list(self._model.embed([text]))[0]
        return result.tolist()

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple texts in batch."""
        if not texts:
            return []
        # For indexing, multilingual-e5 uses "passage: " prefix
        if "e5" in self._model_name:
            texts = [f"passage: {t}" if not t.startswith("passage:") else t for t in texts]
        results = list(self._model.embed(texts))
        return [r.tolist() for r in results]
