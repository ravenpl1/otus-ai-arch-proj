"""API routes — FastAPI router definitions.

Endpoints convert between HTTP schemas and use case DTOs,
delegating business logic to the use case layer.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, UploadFile, File, Depends
from pydantic import BaseModel, Field

from presentation.auth import AuthenticatedUser, get_current_user, get_optional_user, require_role

from presentation.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatChoice,
    ChatChoiceMessage,
    IngestResponse,
    HealthResponse,
    IngestRFSDBatchRequest,
    IngestRFSDBatchResponse,
)
from application.use_cases.chat_completion import (
    ChatCompletionInput,
    ChatMessage,
    execute_chat_completion,
)
from application.use_cases.ingest_documents import (
    IngestInput,
    execute_ingest_documents,
)
from application.use_cases.ingest_rfsd import execute_ingest_rfsd, execute_ingest_rfsd_batch
from infrastructure.adapters.file_loader import load_file

import logging
import httpx

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# OAuth2 Token Proxy — exchanges authorization code for access_token
# server-side, bypassing browser CORS restrictions with Authelia.
# ---------------------------------------------------------------------------

class TokenRequest(BaseModel):
    grant_type: str = Field(default="authorization_code")
    code: str
    redirect_uri: str
    client_id: str = Field(default="fastapi-swagger")
    code_verifier: str | None = None


@router.post("/auth/token")
async def proxy_token(request: TokenRequest):
    """Proxy token exchange to OIDC provider (bypasses browser CORS)."""
    from config.settings import OIDC_ISSUER_URL

    token_url = f"{OIDC_ISSUER_URL}/api/oidc/token"

    form_data = {
        "grant_type": request.grant_type,
        "code": request.code,
        "redirect_uri": request.redirect_uri,
        "client_id": request.client_id,
    }
    if request.code_verifier:
        form_data["code_verifier"] = request.code_verifier

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(token_url, data=form_data, timeout=30.0)
            return resp.json()
        except httpx.ConnectError:
            logger.error("Authelia unreachable at %s", token_url)
            return {"error": "authelia_unavailable"}
        except Exception as e:
            logger.error("Token exchange failed: %s", e)
            return {"error": str(e)}


@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok")


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    user: AuthenticatedUser | None = Depends(get_optional_user),
):
    from presentation.app import get_agent

    agent = get_agent(model=request.model)

    # Use role from JWT token if authenticated, otherwise from request body
    user_role = user.role if user else request.user_role

    logger.info("Route: model=%s, messages_count=%d, roles=%s",
                request.model, len(request.messages), [m.role for m in request.messages])
    for m in request.messages:
        logger.info("Route message: role=%s, content=%s", m.role, m.content[:50])

    use_case_input = ChatCompletionInput(
        messages=[ChatMessage(role=m.role, content=m.content) for m in request.messages],
        model=request.model,
        temperature=request.temperature,
        user_role=user_role,
    )

    result = execute_chat_completion(agent, use_case_input)

    return ChatCompletionResponse(
        id=result.id,
        object=result.object,
        created=result.created,
        model=result.model,
        choices=[ChatChoice(message=ChatChoiceMessage(content=result.content), finish_reason=result.finish_reason)],
    )


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    files: List[UploadFile] = File(...),
    user: AuthenticatedUser = Depends(require_role("DATA_STEWARD", "ADMIN")),
):
    from presentation.app import get_embedder, get_vector_store, get_graph_store, get_settings

    embedder = get_embedder()
    vector_store = get_vector_store()
    graph_store = get_graph_store()
    settings = get_settings()

    file_paths: List[str] = []
    file_names: List[str] = []

    try:
        for upload_file in files:
            suffix = Path(upload_file.filename).suffix
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode="wb") as tmp:
                content = await upload_file.read()
                tmp.write(content)
                file_paths.append(tmp.name)
                file_names.append(upload_file.filename)

        # Load documents via infrastructure adapter
        from domain.entities import Document
        all_documents: List[Document] = []
        for file_path, file_name in zip(file_paths, file_names):
            doc = load_file(file_path)
            doc.source = file_name
            all_documents.append(doc)

        # Execute use case with pre-loaded documents
        use_case_input = IngestInput(file_paths=file_paths, file_names=file_names)
        result = execute_ingest_documents(
            use_case_input,
            documents=all_documents,
            embedder=embedder,
            vector_store=vector_store,
            graph_store=graph_store,
            collection=settings.infra.qdrant_collection,
        )

        return IngestResponse(
            chunks_indexed=result.chunks_indexed,
            vector_collection=result.vector_collection,
            graph_nodes_created=result.graph_nodes_created,
        )

    finally:
        for path in file_paths:
            try:
                os.unlink(path)
            except OSError:
                pass


class IngestRFSDRequest(BaseModel):
    csv_path: str = Field(..., description="Absolute path to the RFSD CSV file")
    year: int = Field(default=2025, description="Default financial year (if not inferrable from data)")


@router.post("/ingest-rfsd")
async def ingest_rfsd(
    request: IngestRFSDRequest,
    user: AuthenticatedUser = Depends(require_role("DATA_STEWARD", "ADMIN")),
):
    """Load RFSD dataset into Neo4j (graph) + Qdrant (vectors)."""
    from presentation.app import get_embedder, get_vector_store, get_graph_store, get_settings

    embedder = get_embedder()
    vector_store = get_vector_store()
    graph_store = get_graph_store()
    settings = get_settings()

    result = execute_ingest_rfsd(
        csv_path=request.csv_path,
        embedder=embedder,
        vector_store=vector_store,
        graph_store=graph_store,
        collection=settings.infra.qdrant_collection,
        year=request.year,
    )

    return {
        "companies_indexed": result.companies_indexed,
        "financials_indexed": result.financials_indexed,
        "chunks_indexed": result.chunks_indexed,
        "errors": result.errors[:20],
    }


@router.post("/ingest-rfsd/batch", response_model=IngestRFSDBatchResponse)
async def ingest_rfsd_batch(
    request: IngestRFSDBatchRequest,
    user: AuthenticatedUser = Depends(require_role("DATA_STEWARD", "ADMIN")),
):
    """Load RFSD records from JSON payload into Neo4j (graph) + Qdrant (vectors)."""
    from presentation.app import get_embedder, get_vector_store, get_graph_store, get_settings

    embedder = get_embedder()
    vector_store = get_vector_store()
    graph_store = get_graph_store()
    settings = get_settings()

    try:
        result = execute_ingest_rfsd_batch(
            records=request.records,
            embedder=embedder,
            vector_store=vector_store,
            graph_store=graph_store,
            collection=settings.infra.qdrant_collection,
            year=request.year,
        )

        return IngestRFSDBatchResponse(
            companies_indexed=result.companies_indexed,
            financials_indexed=result.financials_indexed,
            chunks_indexed=result.chunks_indexed,
            errors=result.errors[:20],
        )
    except Exception as e:
        logger.exception("Ingest RFSD batch failed")
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal error: {e}", "errors": [str(e)]},
        )
