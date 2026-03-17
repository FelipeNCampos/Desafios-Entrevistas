"""HTTP API for triggering the automation workflow."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.main import AVAILABLE_FILTERS, _run_execution
from app.utils.logs import get_logger


LOGGER = get_logger(__name__)
app = FastAPI(
    title="Portal da Transparencia Bot API",
    version="1.0.0",
    description="API para executar a automacao de consulta e obter os artefatos gerados.",
)


class ExecutionRequest(BaseModel):
    termo: str = Field(..., min_length=1, description="Termo de busca: nome, CPF ou NIS.")
    filtros: list[str] = Field(
        default_factory=list,
        description="Lista de filtros adicionais aceitos pelo portal.",
    )
    output: str = Field(
        default="artifacts",
        description="Diretorio base para salvar os artefatos da execucao.",
    )
    max_results: int | None = Field(
        default=None,
        ge=0,
        description="Limite de resultados processados. Use 0 para processar todos.",
    )
    include_base64: bool = Field(
        default=False,
        description="Inclui a imagem principal em base64 na resposta.",
    )
    include_payload: bool = Field(
        default=False,
        description="Inclui o payload completo da execucao na resposta.",
    )


class ExecutionResponse(BaseModel):
    termo: str
    execution_dir: str
    json_path: str
    summary: dict[str, Any]
    base64: str | None = None
    payload: dict[str, Any] | None = None


@app.get("/health")
def health() -> dict[str, str]:
    """Health endpoint for uptime checks."""
    return {"status": "ok"}


@app.get("/filters")
def list_filters() -> dict[str, list[str]]:
    """List all accepted filter ids."""
    return {"filters": AVAILABLE_FILTERS}


@app.post("/executions", response_model=ExecutionResponse)
def create_execution(request: ExecutionRequest) -> ExecutionResponse:
    """Run the scraper synchronously and return execution metadata."""
    invalid_filters = [item for item in request.filtros if item not in AVAILABLE_FILTERS]
    if invalid_filters:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Filtros invalidos informados.",
                "invalid_filters": invalid_filters,
                "available_filters": AVAILABLE_FILTERS,
            },
        )

    try:
        execution_result = _run_execution(
            termo=request.termo,
            output_path=request.output,
            filtros=request.filtros,
            max_results=request.max_results,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Execution failed for termo=%s", request.termo)
        raise HTTPException(
            status_code=500,
            detail="Falha ao executar a automacao.",
        ) from exc

    return ExecutionResponse(
        termo=request.termo,
        execution_dir=str(execution_result["execution_dir"]),
        json_path=str(execution_result["json_path"]),
        summary=dict(execution_result["summary"]),
        base64=str(execution_result["base64"]) if request.include_base64 else None,
        payload=dict(execution_result["payload"]) if request.include_payload else None,
    )
