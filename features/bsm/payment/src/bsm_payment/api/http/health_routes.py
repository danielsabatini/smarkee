"""Probes da API (decisão 0018): só pela rede interna; o gateway publica apenas `/v1/...`."""

from collections.abc import Callable
from http import HTTPStatus

from fastapi import FastAPI
from fastapi.responses import JSONResponse


def register_health_routes(app: FastAPI, is_ready: Callable[[], bool]) -> None:
    """A liveness não consulta dependências; a readiness inclui o NATS."""

    @app.get("/health/live")
    async def health_live() -> dict[str, str]:
        return {"status": "UP"}

    @app.get("/health/startup")
    async def health_startup() -> dict[str, str]:
        return {"status": "UP"}

    @app.get("/health/ready")
    async def health_ready() -> JSONResponse:
        ready = is_ready()
        return JSONResponse(
            {"status": "UP" if ready else "DOWN", "checks": {"nats": "UP" if ready else "DOWN"}},
            status_code=HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
        )
