"""API application factory — Composition Root.

Wires all infrastructure adapters (outer layer) to the
port interfaces (inner layer) and exposes the assembled app.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from presentation.routes import router
from config.settings import AppSettings
from application.ports import VectorStorePort, GraphStorePort, EmbedderPort
from application.guardrails.input_guardrail import InputGuardrail
from application.guardrails.output_guardrail import OutputGuardrail
from application.agent.nodes import AgentDependencies, set_dependencies

logger = logging.getLogger(__name__)

_app_settings: AppSettings | None = None
_findata_agent: Any = None
_chat_agent: Any = None
_vector_store: VectorStorePort | None = None
_graph_store: GraphStorePort | None = None
_embedder: EmbedderPort | None = None


def get_settings() -> AppSettings:
    if _app_settings is None:
        raise RuntimeError("Settings not initialized.")
    return _app_settings


def get_agent(model: str = "findata-agent"):
    """Get agent by model name: 'findata-agent' or 'chat-agent'."""
    if model == "chat-agent":
        if _chat_agent is None:
            raise RuntimeError("Chat agent not initialized.")
        return _chat_agent
    if _findata_agent is None:
        raise RuntimeError("FinData agent not initialized.")
    return _findata_agent


def get_vector_store() -> VectorStorePort:
    if _vector_store is None:
        raise RuntimeError("Vector store not initialized.")
    return _vector_store


def get_graph_store() -> GraphStorePort:
    if _graph_store is None:
        raise RuntimeError("Graph store not initialized.")
    return _graph_store


def get_embedder() -> EmbedderPort:
    if _embedder is None:
        raise RuntimeError("Embedder not initialized.")
    return _embedder


def _bootstrap_app() -> None:
    global _app_settings, _findata_agent, _chat_agent, _vector_store, _graph_store, _embedder

    from config.settings import (
        OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_NUM_CTX,
        QDRANT_HOST, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD,
        QDRANT_COLLECTION, LLM_TEMPERATURE_GUARDRAILS,
    )
    from langchain_ollama import ChatOllama
    from infrastructure.adapters.vector_store_qdrant import QdrantVectorStore
    from infrastructure.adapters.graph_store_neo4j import Neo4jGraphStore
    from infrastructure.adapters.embedder_fastembed import FastEmbedEmbedder
    from application.agent.graph import build_findata_agent_graph, build_chat_agent_graph

    logging.basicConfig(level=logging.INFO)
    logger.info("=== Bootstrap started ===")

    _app_settings = AppSettings.from_env()

    # Create infrastructure adapters
    _vector_store = QdrantVectorStore(url=QDRANT_HOST)
    _graph_store = Neo4jGraphStore(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
    _embedder = FastEmbedEmbedder()

    # LLM factory
    def llm_factory(temperature: float | None = None) -> ChatOllama:
        return ChatOllama(
            model=OLLAMA_MODEL,
            base_url=OLLAMA_HOST,
            num_ctx=OLLAMA_NUM_CTX,
            reasoning=False,
            temperature=temperature if temperature is not None else 0.0,
            timeout=120,
        )

    # Guardrails
    input_guardrail = InputGuardrail()
    def output_guardrail_factory() -> OutputGuardrail:
        return OutputGuardrail(llm=llm_factory(LLM_TEMPERATURE_GUARDRAILS))

    # Wire agent dependencies
    agent_deps = AgentDependencies(
        llm_factory=llm_factory,
        vector_store=_vector_store,
        graph_store=_graph_store,
        input_guardrail=input_guardrail,
        output_guardrail_factory=output_guardrail_factory,
        embedder=_embedder,
        qdrant_collection=QDRANT_COLLECTION,
    )
    set_dependencies(agent_deps)

    # Verify connectivity
    try:
        _vector_store.check_connectivity()
        logger.info("Qdrant connection OK")
    except Exception as e:
        logger.warning("Qdrant unreachable: %s", e)

    try:
        _graph_store.check_connectivity()
        logger.info("Neo4j connection OK")
    except Exception as e:
        logger.warning("Neo4j unreachable: %s", e)

    # Setup infrastructure
    try:
        _graph_store.init_schema()
        logger.info("Neo4j schema initialized (constraints + IndustrySection seed)")
    except Exception as e:
        logger.warning("Could not init Neo4j schema: %s", e)

    try:
        _vector_store.ensure_collection(QDRANT_COLLECTION, vector_size=384)
        logger.info("Qdrant collection '%s' ready", QDRANT_COLLECTION)
    except Exception as e:
        logger.warning("Could not ensure Qdrant collection: %s", e)

    try:
        _graph_store.ensure_constraints()
        logger.info("Neo4j constraints ready")
    except Exception as e:
        logger.warning("Could not ensure Neo4j constraints: %s", e)

    # Build agents
    _findata_agent = build_findata_agent_graph()
    logger.info("FinData agent graph compiled")
    _chat_agent = build_chat_agent_graph()
    logger.info("Chat agent graph compiled")
    logger.info("=== Bootstrap completed ===")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _bootstrap_app()
    yield
    if _graph_store is not None and hasattr(_graph_store, 'close'):
        _graph_store.close()


def create_app() -> FastAPI:
    from config.settings import OIDC_ISSUER_URL_BROWSER, OIDC_CLIENT_ID

    app = FastAPI(
        title="RFSD RAG Agent API",
        description="Graph RAG agent with guardrails + RBAC + document ingestion (RFSD dataset)",
        version="0.3.0",
        lifespan=lifespan,
        swagger_ui_init_oauth={
            "clientId": OIDC_CLIENT_ID,
            "appName": "RFSD RAG Agent",
            "scopes": "openid profile groups email",
            "usePkceWithAuthorizationCodeGrant": True,
        },
    )
    app.include_router(router)

    # Custom OpenAPI schema with OAuth2 security
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        from fastapi.openapi.utils import get_openapi
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        schema["components"]["securitySchemes"] = {
            "OAuth2": {
                "type": "oauth2",
                "description": "OIDC Authorization Code + PKCE (Authelia, Keycloak, Auth0, etc.)",
                "flows": {
                    "authorizationCode": {
                            "authorizationUrl": f"{OIDC_ISSUER_URL_BROWSER}/api/oidc/authorization",
                        "tokenUrl": f"{OIDC_ISSUER_URL_BROWSER}/api/oidc/token",
                        "scopes": {
                            "openid": "OpenID Connect",
                            "profile": "User profile",
                            "groups": "User groups (roles)",
                            "email": "User email",
                        },
                    }
                },
            },
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "Paste JWT token from OIDC flow",
            },
        }
        schema["security"] = [{"OAuth2": ["openid", "profile", "groups"]}]

        # Remove HTTPBearer auto-generated scheme (conflicts with OAuth2)
        if "securitySchemes" in schema.get("components", {}):
            schema["components"]["securitySchemes"].pop("HTTPBearer", None)

        # Ensure all operations use OAuth2 (Swagger UI will auto-send the access_token)
        # Skip public endpoints that don't require authentication
        _public_paths = {"/health", "/auth/token", "/openapi.json"}
        for path, path_item in schema.get("paths", {}).items():
            if path in _public_paths:
                continue
            for method in ("get", "post", "put", "delete", "patch", "head", "options"):
                op = path_item.get(method)
                if op and isinstance(op, dict):
                    op["security"] = [{"OAuth2": ["openid", "profile", "groups"]}]

        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = custom_openapi

    return app
