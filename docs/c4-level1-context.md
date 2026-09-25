# C4 Level 1 — Context Diagram

## RFSD RAG Agent — System Context

```mermaid
C4Context
    title System Context Diagram — RFSD RAG Agent

    Person(user, "Пользователь", "Задаёт вопросы о финансовых\nданных компаний РФ")
    Person(data_steward, "Дата Стюард", "Загружает данные RFSD\nскриптом ingest_rfsd.py\nили через API")

    System(authelia, "Authelia", "OIDC Provider.\nАутентификация\nпользователей,\nуправление группами\nи ролями.")

    System(rag_agent, "RFSD RAG Agent", "Graph RAG агент с guardrails.\nДва режима: RAG (поиск+LLM)\nи Chat (прямой диалог).\nNeo4j-first GraphRAG pipeline.")

    System(ollama, "Ollama Server", "Локальный LLM serving\n(Qwen 3.5-9B GGUF Q4_0)")

    System(rfsd_csv, "RFSD Dataset", "CSV-файл с финансовыми\nданными компаний РФ\n(ИНН, выручка, активы, ...)\n2023-2025")

    System_Ext(otel, "Observability Stack", "OpenTelemetry + Prometheus\n+ Grafana + Jaeger")

    Rel(user, authelia, "OIDC Login\n(Authorization Code\n+ PKCE)", "HTTPS")
    Rel(data_steward, authelia, "OIDC Login", "HTTPS")
    Rel(user, rag_agent, "POST /v1/chat/completions\nBearer JWT token\nmode=rag|chat", "HTTPS/JSON")
    Rel(data_steward, rag_agent, "POST /ingest-rfsd\nBearer JWT token", "HTTPS/JSON")
    Rel(data_steward, rag_agent, "POST /ingest\nBearer JWT token", "HTTPS/JSON")
    Rel(data_steward, rfsd_csv, "scripts/ingest_rfsd.py\n--token=... --csv-path=...", "CLI")

    Rel(rag_agent, authelia, "JWT validation\n(JWKS endpoint)", "HTTPS")
    Rel(rag_agent, ollama, "LLM inference\n(промпт → ответ)", "HTTP/JSON")

    Rel(rag_agent, otel, "Traces, Metrics, Logs", "OTLP/gRPC")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Описание

| Актёр/Система | Роль |
|---|---|
| **Пользователь** | Отправляет вопросы через REST API. Авторизуется через Authelia (OIDC). Роль определяется из JWT. Два режима: `rag` (поиск в графе + LLM) и `chat` (прямой диалог с LLM). |
| **Дата Стюард** | Загружает RFSD CSV через скрипт `scripts/ingest_rfsd.py` или API endpoint `/ingest-rfsd`. Только с ролью DATA_STEWARD. |
| **Authelia** | OIDC Provider — аутентификация, управление пользователями и группами. Выдаёт JWT-токены. |
| **RFSD RAG Agent** | Graph RAG агент: Neo4j-first поиск компании → Qdrant текст → Neo4j финансовые данные → LLM ответ. Guardrails + RBAC. |
| **Ollama Server** | Локальный LLM serving на базе Qwen 3.5-9B (GGUF Q4_0). Reasoning отключён (`/no_think`). |
| **RFSD Dataset** | CSV-файл с финансовыми данными ~600К компаний РФ за 2023-2025 гг. |
| **Observability Stack** | Сбор трейсов, метрик и логов через OpenTelemetry Collector. |
