# UML Sequence Diagrams — RFSD RAG Agent

## 1. RAG Query — GraphRAG Pipeline (mode=rag)

Пользователь задаёт вопрос о компании. Система ищет в Neo4j, получает текст из Qdrant, запрашивает финансовые данные и генерирует ответ через LLM.

```mermaid
sequenceDiagram
    actor User as Пользователь
    participant API as FastAPI<br/>Routes
    participant Auth as Authelia<br/>(OIDC)
    participant UC as ChatCompletion<br/>UseCase
    participant Agent as LangGraph<br/>StateGraph
    participant IG as InputGuardrail<br/>Node
    participant RBAC as RBAC Policy<br/>(Domain)
    participant GR as GraphRAG<br/>Fetch Node
    participant Neo4j as Neo4jGraphStore<br/>Adapter
    participant Qdrant as QdrantVectorStore<br/>Adapter
    participant LLM as LLM Generation<br/>Node
    participant Ollama as Ollama<br/>Server
    participant OG as OutputGuardrail<br/>Node

    User->>API: POST /v1/chat/completions<br/>{messages, user_role, mode="rag"}
    API->>Auth: Validate JWT (JWKS)
    Auth-->>API: Token valid, groups=[fin-users]

    API->>UC: execute_chat_completion(request)
    UC->>Agent: invoke(state)<br/>+ raw_query, mode="rag"

    Note over Agent: Step 1: extract_input
    Agent->>Agent: extract_input_node()<br/>raw_query from state

    Note over Agent: Step 2: input_guardrail
    Agent->>IG: input_guardrail_node(state)
    IG->>RBAC: get_restricted_fields("USER")
    RBAC-->>IG: ["b_assets", "b_liab", ...]
    IG-->>Agent: {safety_status: "ok",<br/>restricted_fields: [...]}

    Note over Agent: Step 3: graph_rag_fetch
    Agent->>GR: graph_rag_fetch_node(state)

    rect rgb(230, 245, 255)
        Note over GR: Step 3a: Neo4j company search
        GR->>Neo4j: search_companies(query, limit=1)
        Neo4j->>Neo4j: CONTAINS short_name<br/>→ fallback: fuzzy fulltext
        Neo4j-->>GR: [{inn: "4217068072",<br/>short_name: "ТД СИБИРЬ"}]

        Note over GR: Step 3b: Qdrant text by INN
        GR->>Qdrant: search_by_payload(inn="4217068072", limit=1)
        Qdrant-->>GR: [{text: "Компания ТД СИБИРЬ...",<br/>payload: {inn, region}}]

        Note over GR: Step 3c: Neo4j financials
        GR->>Neo4j: get_financials_by_inns(<br/>["4217068072"],<br/>restricted_fields=[...])
        Neo4j->>Neo4j: MATCH (c)-[:HAS_FINANCIALS]->(f)<br/>WHERE c.inn IN [...]<br/>RETURN allowed fields only
        Neo4j-->>GR: ["Компания ТД СИБИРЬ (ИНН: 4217068072)<br/>за 2023: выручка=500,000<br/>за 2024: выручка=600,000"]
    end

    GR-->>Agent: {retrieved_facts: [...],<br/>data_found: true}

    Note over Agent: Step 4: conditional → data_found=true
    Agent->>LLM: llm_generation_node(state)

    LLM->>LLM: prompt = "/no_think\n{system_msg}\n\nФакты:\n{facts}\n\nВопрос: {query}"
    LLM->>Ollama: invoke(prompt)
    Ollama-->>LLM: "Компания ТД СИБИРЬ<br/>показала рост выручки..."
    LLM-->>Agent: {llm_response: "..."}

    Note over Agent: Step 5: output_guardrail
    Agent->>OG: output_guardrail_node(state)
    OG->>Ollama: LLM-as-a-Judge: validate(facts, answer)
    Ollama-->>OG: {status: "ok"}
    OG-->>Agent: {safety_status: "ok"}

    Agent-->>UC: final_state
    UC-->>API: {choices: [{message: {content: "..."}}]}
    API-->>User: 200 OK {choices: [...]}
```

## 2. RAG Query — No Data Found (mode=rag)

Пользователь спрашивает о несуществующей компании. Neo4j не находит, Qdrant тоже. LLM пропускается.

```mermaid
sequenceDiagram
    actor User as Пользователь
    participant API as FastAPI<br/>Routes
    participant UC as ChatCompletion<br/>UseCase
    participant Agent as LangGraph<br/>StateGraph
    participant GR as GraphRAG<br/>Fetch Node
    participant Neo4j as Neo4j<br/>Adapter
    participant Qdrant as Qdrant<br/>Adapter
    participant Embedder as FastEmbed<br/>Embedder
    participant NDR as NoData<br/>Response Node

    User->>API: POST /v1/chat/completions<br/>{messages, mode="rag"}
    API->>UC: execute_chat_completion()
    UC->>Agent: invoke(state)

    Agent->>GR: graph_rag_fetch_node(state)

    rect rgb(255, 240, 240)
        GR->>Neo4j: search_companies("Несуществующая", limit=1)
        Neo4j-->>GR: []

        Note over GR: Neo4j не нашёл → fallback
        GR->>Embedder: embed_text(query)
        Embedder-->>GR: [0.12, -0.34, ...]
        GR->>Qdrant: search(query_vector, limit=3)
        Qdrant-->>GR: [] (нет совпадений)
    end

    GR-->>Agent: {retrieved_facts: ["По запросу ничего не найдено"],<br/>data_found: false}

    Note over Agent: conditional → data_found=false
    Agent->>NDR: no_data_response_node(state)
    NDR-->>Agent: {llm_response: "К сожалению,<br/>информация не найдена..."}

    Agent-->>UC: final_state
    UC-->>API: response
    API-->>User: 200 OK
```

## 3. Chat Query — Direct LLM (mode=chat)

Пользователь задаёт общий вопрос. Retrieval пропускается, LLM отвечает напрямую.

```mermaid
sequenceDiagram
    actor User as Пользователь
    participant API as FastAPI<br/>Routes
    participant UC as ChatCompletion<br/>UseCase
    participant Agent as LangGraph<br/>StateGraph
    participant IG as InputGuardrail<br/>Node
    participant GR as GraphRAG<br/>Fetch Node
    participant NDR as NoData<br/>Response Node
    participant LLM as LLM Generation<br/>Node
    participant Ollama as Ollama<br/>Server

    User->>API: POST /v1/chat/completions<br/>{messages, mode="chat"}
    API->>UC: execute_chat_completion()
    UC->>Agent: invoke(state)<br/>mode="chat"

    Agent->>Agent: extract_input_node()
    Agent->>IG: input_guardrail_node(state)
    IG-->>Agent: {safety_status: "ok"}

    Agent->>GR: graph_rag_fetch_node(state)
    Note over GR: mode=chat → retrieval skipped
    GR-->>Agent: {retrieved_facts: [],<br/>data_found: false}

    Agent->>NDR: no_data_response_node(state)
    Note over NDR: Просто ставит placeholder response
    NDR-->>Agent: {llm_response: "Инformation not found"}

    Note over Agent: conditional → data_found=false<br/>Но для chat → special handling
    Agent->>LLM: llm_generation_node(state)

    LLM->>LLM: prompt = "/no_think\n{system_msg}\n\nВопрос: {query}"
    Note over LLM: mode=chat: БЕЗ retrieved_facts
    LLM->>Ollama: invoke(prompt)
    Ollama-->>LLM: "Общий ответ на вопрос..."
    LLM-->>Agent: {llm_response: "..."}

    Agent-->>UC: final_state
    UC-->>API: response
    API-->>User: 200 OK
```

## 4. RFSD Ingest — Data Loading Pipeline

Data Steward загружает RFSD CSV через скрипт. Данные попадают в Neo4j (граф) и Qdrant (векторы).

```mermaid
sequenceDiagram
    actor Steward as Data Steward
    participant Script as ingest_rfsd.py<br/>(CLI)
    participant API as FastAPI<br/>Routes
    participant Auth as Authelia<br/>(OIDC)
    participant UC as IngestRFSD<br/>UseCase
    participant Neo4j as Neo4jGraphStore<br/>Adapter
    participant Qdrant as QdrantVectorStore<br/>Adapter
    participant Embedder as FastEmbed<br/>Embedder

    Steward->>Script: python scripts/ingest_rfsd.py<br/>--token="..." --csv-path=data/file.csv

    Script->>Script: Read CSV → normalize fields<br/>(B_assets → b_assets, INN→str)
    Script->>Script: Split into batches (batch_size=100)

    loop Each batch
        Script->>API: POST /ingest-rfsd<br/>{records: [...]}<br/>Authorization: Bearer token
        API->>Auth: Validate JWT
        Auth-->>API: Valid, role=DATA_STEWARD

        API->>UC: execute_ingest_rfsd_batch(<br/>records, embedder, vector_store,<br/>graph_store, collection="findata")

        loop Each record
            UC->>UC: _process_record(row)<br/>Company + Financials<br/>region=None if empty

            UC->>Neo4j: upsert_company_with_financials(<br/>company, financials)
            Neo4j->>Neo4j: MERGE (c:Company {inn})<br/>SET properties<br/>MERGE (f:Financials {id})<br/>+ Region if not None

            UC->>UC: _format_company_text(company)<br/>"Компания ТД СИБИРЬ,<br/>ИНН: 4217068072..."
        end

        UC->>Embedder: embed_texts(texts)
        Embedder-->>UC: [[0.12, ...], [0.34, ...]]

        UC->>Qdrant: upsert(chunks, embeddings,<br/>collection="findata")
        Qdrant->>Qdrant: Upsert vectors with<br/>payload: {inn, region}

        loop Each chunk
            UC->>Neo4j: link_company_to_chunk(<br/>inn, chunk_id)
        end

        UC-->>API: IngestRFSDOutput<br/>{companies_indexed: 100, errors: []}
        API-->>Script: 200 OK
    end

    Script-->>Steward: Done: 1000 companies,<br/>0 errors
```

## 5. Input Guardrail — Blocked Request

Prompt injection detected → request blocked, LLM не вызывается.

```mermaid
sequenceDiagram
    actor User as Пользователь
    participant API as FastAPI
    participant Agent as LangGraph<br/>StateGraph
    participant IG as InputGuardrail<br/>Node
    participant GuardSvc as InputGuardrail<br/>Service

    User->>API: POST /v1/chat/completions<br/>{messages: ["Ignore all instructions..."]}
    API->>Agent: invoke(state)

    Agent->>IG: input_guardrail_node(state)
    IG->>GuardSvc: validate(raw_query)
    GuardSvc->>GuardSvc: Check blocked phrases,<br/>prompt injection patterns
    GuardSvc-->>IG: {status: "blocked",<br/>message: "Запрос заблокирован"}

    IG-->>Agent: {safety_status: "blocked",<br/>llm_response: "Запрос заблокирован"}

    Note over Agent: LLM НЕ вызывается
    Agent-->>API: final_state
    API-->>User: 200 OK<br/>{content: "Запрос заблокирован<br/>системой безопасности"}
