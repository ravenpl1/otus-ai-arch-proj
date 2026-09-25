# C4 Level 2 — Container Diagram

## RFSD RAG Agent — Containers

```mermaid
C4Container
    title Container Diagram — RFSD RAG Agent

    Person(user, "Пользователь", "Задаёт вопросы о финансовых данных (rag|chat)")
    Person(data_steward, "Дата Стюард", "Загружает RFSD CSV скриптом или API")

    System_Boundary(rag_system, "RFSD RAG Agent") {
        Container(fastapi, "FastAPI Application", "Python 3.12, FastAPI", "REST API: chat completions, ingest, ingest-rfsd, health. JWT validation + RBAC.")
        Container(langgraph, "LangGraph Agent", "Python, LangGraph StateGraph", "Neo4j-first GraphRAG: Neo4j search -> Qdrant text -> Neo4j financials -> LLM. Два режима: rag / chat.")
        Container(ingest_script, "ingest_rfsd.py", "Python CLI requests library", "Загрузка CSV в Neo4j+Qdrant через REST API. Auth: bearer token.")
        Container(neo4j, "Neo4j", "Neo4j 5.x Graph Database", "Граф знаний: Company, Financials, Region, IndustrySection, Chunk + fulltext index")
        Container(qdrant, "Qdrant", "Qdrant Vector Database", "Векторные embeddings: текстовые описания компаний БЕЗ чисел. Payload: inn, region.")
    }

    System(authelia, "Authelia", "OIDC Provider JWT issuance + JWKS validation")
    System(ollama, "Ollama Server", "LLM serving Qwen 3.5-9B GGUF Q4_0 /no_think mode")
    System_Ext(grafana, "Grafana + Jaeger", "Визуализация метрик и трейсов")
    System_Ext(otel_collector, "OpenTelemetry Collector", "Сбор метрик и трейсов")

    Rel(user, authelia, "OIDC Login (Authorization Code + PKCE)", "HTTPS")
    Rel(data_steward, authelia, "OIDC Login", "HTTPS")
    Rel(user, fastapi, "POST /v1/chat/completions Bearer JWT mode=rag|chat", "HTTPS/JSON")
    Rel(data_steward, fastapi, "POST /ingest-rfsd Bearer JWT", "HTTPS/JSON")
    Rel(data_steward, ingest_script, "python scripts/ingest_rfsd.py --token=...", "CLI")
    Rel(ingest_script, fastapi, "POST /ingest-rfsd Bearer JWT", "HTTPS/JSON")
    Rel(fastapi, authelia, "JWT validation (JWKS)", "HTTPS")
    Rel(fastapi, langgraph, "invoke(agent, state) Messages + user_role + mode", "Python call")
    Rel(langgraph, neo4j, "Cypher queries: init_schema, search_companies (fulltext), upsert_company, get_financials_by_inns", "Bolt protocol")
    Rel(langgraph, qdrant, "search, search_by_payload, upsert embeddings", "gRPC/REST")
    Rel(langgraph, ollama, "Chat completion: prompt -> response (/no_think)", "HTTP/JSON")
    Rel(fastapi, otel_collector, "Traces, Metrics", "OTLP/gRPC")
```

## Описание контейнеров

| Контейнер | Технология | Назначение |
|---|---|---|
| **FastAPI Application** | Python 3.12, FastAPI, Pydantic | REST API: `/v1/chat/completions`, `/ingest`, `/ingest-rfsd`, `/health`. JWT validation + RBAC. |
| **LangGraph Agent** | Python, LangGraph StateGraph | Neo4j-first GraphRAG pipeline: 5 нод с conditional edges. Два режима: `rag` (retrieval+LLM) и `chat` (прямой LLM). |
| **ingest_rfsd.py** | Python CLI, requests | Скрипт загрузки RFSD CSV через REST API. Авторизация bearer token. |
| **Authelia** | Authelia 4.38 | OIDC Provider: аутентификация, управление пользователями/группами, выдаёт JWT. |
| **Neo4j** | Neo4j 5.x | Граф знаний: Company, Financials, Region, IndustrySection, Chunk. Fuzzy fulltext search по названию. RBAC на уровне Cypher. |
| **Qdrant** | Qdrant | Векторная БД: текстовые описания компаний. Поиск по вектору (semantic) и по payload (INN). |
| **Ollama Server** | Ollama + Qwen 3.5-9B | Локальный LLM serving. GGUF Q4_0. `/no_think` mode для отключения reasoning. |

## Data Flow: GraphRAG Query (mode=rag)

```
1. User → FastAPI: POST /v1/chat/completions {messages, user_role, mode="rag"}
2. FastAPI → LangGraph: invoke(state)
3. extract_input → input_guardrail (RBAC: restricted_fields)
4. graph_rag_fetch:
   4a. Neo4j: search_companies(query, limit=1) → [Company{inn, name}]
   4b. Qdrant: search_by_payload(inn) → text description
   4c. Neo4j: get_financials_by_inns([inn], restricted_fields) → [facts]
   4d. Fallback: Qdrant semantic search → INN → Neo4j
5. Conditional: data_found?
   - Yes → llm_generation: prompt(facts + /no_think + question) → answer
   - No  → no_data_response: "Инformation not found"
6. output_guardrail: validate(facts, answer)
7. FastAPI → User: {choices: [{message: {content: answer}}]}
```

## Data Flow: Chat Query (mode=chat)

```
1. User → FastAPI: POST /v1/chat/completions {messages, user_role, mode="chat"}
2. FastAPI → LangGraph: invoke(state)
3. extract_input → input_guardrail
4. graph_rag_fetch: SKIP (mode=chat, data_found=false)
5. no_data_response → llm_generation: prompt(/no_think + question) → answer
6. FastAPI → User: {choices: [{message: {content: answer}}]}
