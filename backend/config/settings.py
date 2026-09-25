"""Application configuration — all settings via environment variables.

Settings are grouped into logical dataclasses for better organization.
Module-level constants provide backward-compatible access for simple use cases.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


# ==========================================
# INFRASTRUCTURE SETTINGS
# ==========================================
@dataclass(frozen=True)
class InfraConfig:
    """External infrastructure connection settings."""

    ollama_host: str
    ollama_model: str
    ollama_num_ctx: int
    qdrant_host: str
    qdrant_collection: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str

    @classmethod
    def from_env(cls) -> InfraConfig:
        return cls(
            ollama_host=os.getenv("OLLAMA_URL", "http://192.168.1.55:11434"),
            ollama_model=os.getenv("OLLAMA_MODEL", "hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_0"),
            ollama_num_ctx=int(os.getenv("OLLAMA_NUM_CTX", "2048")),
            qdrant_host=os.getenv("QDRANT_URL", "http://192.168.1.55:6333"),
            qdrant_collection=os.getenv("QDRANT_COLLECTION", "findata"),
            neo4j_uri=os.getenv("NEO4J_URI", "bolt://192.168.1.55:7687"),
            neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
            neo4j_password=os.getenv("NEO4J_PASSWORD", "password123"),
        )


# ==========================================
# OBSERVABILITY SETTINGS
# ==========================================
@dataclass(frozen=True)
class ObservabilityConfig:
    """Observability and tracing settings."""

    otel_endpoint: str
    app_name: str

    @classmethod
    def from_env(cls) -> ObservabilityConfig:
        return cls(
            otel_endpoint=os.getenv("OTEL_ENDPOINT", "http://192.168.1.55:4318"),
            app_name=os.getenv("APP_NAME", "langgraph-qwen-agent"),
        )


# ==========================================
# GUARDRAIL SETTINGS
# ==========================================
@dataclass(frozen=True)
class GuardrailConfig:
    """Input/output guardrail settings."""

    blocked_phrases: tuple[str, ...]
    llm_temperature: float

    @classmethod
    def from_env(cls) -> GuardrailConfig:
        return cls(
            blocked_phrases=(
                "забудь инструкции",
                "forget instructions",
                "ignore previous",
            ),
            llm_temperature=0.0,  # Deterministic for safety checks
        )


# ==========================================
# INGESTION SETTINGS
# ==========================================
@dataclass(frozen=True)
class IngestionConfig:
    """Document ingestion and chunking settings."""

    chunk_size: int
    chunk_overlap: int

    @classmethod
    def from_env(cls) -> IngestionConfig:
        return cls(
            chunk_size=int(os.getenv("CHUNK_SIZE", "500")),
            chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "50")),
        )


# ==========================================
# LLM SETTINGS
# ==========================================
@dataclass(frozen=True)
class LLMConfig:
    """LLM generation settings."""

    system_prompt: str
    temperature_generation: float

    @classmethod
    def from_env(cls) -> LLMConfig:
        return cls(
            system_prompt=os.getenv(
                "SYSTEM_PROMPT",
                "Ты — полезный ассистент. Отвечай строго на основе предоставленных фактов. "
                "Если фактов недостаточно, скажи об этом честно.",
            ),
            temperature_generation=float(os.getenv("LLM_TEMPERATURE_GENERATION", "0.7")),
        )


# ==========================================
# APPLICATION SETTINGS (aggregate)
# ==========================================
@dataclass(frozen=True)
class AppSettings:
    """Aggregate application settings — single entry point."""

    infra: InfraConfig
    observability: ObservabilityConfig
    guardrails: GuardrailConfig
    ingestion: IngestionConfig
    llm: LLMConfig

    @classmethod
    def from_env(cls) -> AppSettings:
        return cls(
            infra=InfraConfig.from_env(),
            observability=ObservabilityConfig.from_env(),
            guardrails=GuardrailConfig.from_env(),
            ingestion=IngestionConfig.from_env(),
            llm=LLMConfig.from_env(),
        )


# ==========================================
# MODULE-LEVEL CONSTANTS (backward compatible)
# ==========================================
# Infrastructure
OLLAMA_HOST: str = os.getenv("OLLAMA_URL", "http://192.168.1.55:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3.5-9b")
OLLAMA_NUM_CTX: int = int(os.getenv("OLLAMA_NUM_CTX", "2048"))

QDRANT_HOST: str = os.getenv("QDRANT_URL", "http://192.168.1.55:6333")
QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION", "findata")

NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://192.168.1.55:7687")
NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password123")

# Observability
OTEL_ENDPOINT: str = os.getenv("OTEL_ENDPOINT", "http://192.168.1.55:4318")
APP_NAME: str = os.getenv("APP_NAME", "langgraph-qwen-agent")

# System prompt
SYSTEM_PROMPT: str = os.getenv(
    "SYSTEM_PROMPT",
    "Ты — полезный ассистент. Отвечай строго на основе предоставленных фактов. "
    "Если фактов недостаточно, скажи об этом честно.",
)

# System prompt for plain chat mode (no retrieval)
SYSTEM_PROMPT_CHAT: str = os.getenv(
    "SYSTEM_PROMPT_CHAT",
    "Ты — полезный ассистент. Отвечай кратко и по делу на русском языке. "
    "Если не знаешь ответа — честно скажи об этом.",
)

# LLM temperature
LLM_TEMPERATURE_GUARDRAILS: float = 0.0
LLM_TEMPERATURE_GENERATION: float = float(os.getenv("LLM_TEMPERATURE_GENERATION", "0.7"))

# Guardrails
BLOCKED_PHRASES: list[str] = [
    "забудь инструкции",
    "forget instructions",
    "ignore previous",
]

# Ingestion
CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "50"))

# OIDC Identity Provider (Authelia, Keycloak, Auth0, Dex, etc.)
# Backend-to-Authelia URL (from Ubuntu VM → Mac OrbStack)
OIDC_ISSUER_URL: str = os.getenv("OIDC_ISSUER_URL", "http://192.168.1.50:9091")
# Browser-to-Authelia URL (Mac browser → localhost)
OIDC_ISSUER_URL_BROWSER: str = os.getenv("OIDC_ISSUER_URL_BROWSER", "http://localhost:9091")
OIDC_CLIENT_ID: str = os.getenv("OIDC_CLIENT_ID", "fastapi-swagger")
