"""Unit tests for use cases — chat completion and document chunking.

Tests use cases with mock dependencies via domain ports.
No real Qdrant, Neo4j, or LLM needed.
"""

from unittest.mock import MagicMock

from domain.entities import Document, Chunk, GuardrailResult
from application.ports import VectorStorePort, GraphStorePort, EmbedderPort
from application.use_cases.chat_completion import (
    ChatCompletionInput,
    ChatMessage,
    execute_chat_completion,
)
from application.chunker import chunk_document


# ==========================================
# MOCK ADAPTERS
# ==========================================
class MockVectorStore(VectorStorePort):
    def __init__(self):
        self.upserted = []

    def search(self, query_vector, collection, limit):
        return [{"id": "chunk_0", "score": 0.9, "payload": {"id": "chunk_0"}}]

    def upsert(self, chunks, embeddings, collection):
        self.upserted.extend(chunks)

    def ensure_collection(self, collection, vector_size):
        pass


class MockGraphStore(GraphStorePort):
    def __init__(self):
        self.indexed = []

    def filter_chunks_by_clearance(self, chunk_ids, clearance):
        return ["Mock fact from graph"]

    def index_chunks(self, chunks, default_clearance=1):
        self.indexed.extend(chunks)

    def ensure_constraints(self):
        pass

    def check_connectivity(self):
        pass


class MockEmbedder(EmbedderPort):
    def embed_text(self, text):
        return [0.1, 0.2, 0.3]

    def embed_texts(self, texts):
        return [self.embed_text(t) for t in texts]


# ==========================================
# CHAT COMPLETION USE CASE TESTS
# ==========================================
class TestChatCompletionUseCase:
    def test_basic_chat(self):
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [MagicMock(content="Mock answer")]
        }

        request = ChatCompletionInput(
            messages=[ChatMessage(role="user", content="Hello")],
            model="test-model",
            temperature=0.5,
        )

        result = execute_chat_completion(mock_agent, request)

        assert result.model == "test-model"
        assert result.content == "Mock answer"
        assert result.finish_reason == "stop"
        assert result.id.startswith("chatcmpl-")
        mock_agent.invoke.assert_called_once()

    def test_system_prompt_included(self):
        captured_inputs = {}
        mock_agent = MagicMock()

        def capture_invoke(inputs):
            captured_inputs.update(inputs)
            return {"messages": [MagicMock(content="Response")]}

        mock_agent.invoke.side_effect = capture_invoke

        request = ChatCompletionInput(
            messages=[
                ChatMessage(role="system", content="Custom system prompt"),
                ChatMessage(role="user", content="Question"),
            ],
        )

        execute_chat_completion(mock_agent, request)

        messages = captured_inputs["messages"]
        assert any("Custom system prompt" in m.content for m in messages)


# ==========================================
# CHUNKER TESTS
# ==========================================
class TestChunker:
    def test_chunk_document(self):
        doc = Document(content="A" * 1000, source="test.txt", doc_type="txt")
        chunks = chunk_document(doc, chunk_size=300, chunk_overlap=50)

        assert len(chunks) > 1
        assert all(isinstance(c, Chunk) for c in chunks)
        assert all(c.source == "test.txt" for c in chunks)
        assert chunks[0].chunk_index == 0
        assert chunks[1].chunk_index == 1

    def test_chunk_document_small(self):
        doc = Document(content="Short text", source="small.txt", doc_type="txt")
        chunks = chunk_document(doc, chunk_size=500, chunk_overlap=50)

        assert len(chunks) == 1
        assert chunks[0].text == "Short text"


# ==========================================
# DOMAIN ENTITY TESTS
# ==========================================
class TestDomainEntities:
    def test_document_creation(self):
        doc = Document(content="Hello", source="test.txt", doc_type="txt")
        assert doc.content == "Hello"
        assert doc.metadata == {}

    def test_chunk_creation(self):
        chunk = Chunk(id="chunk_0", text="Some text", source="file.txt", chunk_index=0)
        assert chunk.security_clearance_level == 1

    def test_guardrail_result_creation(self):
        result = GuardrailResult(status="ok")
        assert result.message is None
