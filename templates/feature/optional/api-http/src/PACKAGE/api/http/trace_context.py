"""Contexto de trace da requisição (decisão 0055).

O gateway inicia o trace e injeta o `traceparent` na requisição para o upstream (decisão 0054). Este
middleware o associa ao contexto da requisição para que os logs tragam o `trace_id` e para que a
publicação no NATS o repasse. É ASGI puro de propósito: o `BaseHTTPMiddleware` executa a rota em
outra task e o contexto não chegaria até ela. Um `traceparent` ausente ou inválido não gera trace
aqui: a requisição segue sem contexto.
"""

from starlette.types import ASGIApp, Receive, Scope, Send

from @@PACKAGE@@.common.logging_config import TRACEPARENT_HEADER, bind_traceparent

_HEADER_NAME = TRACEPARENT_HEADER.encode("ascii")


class TraceContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            raw = next((v for k, v in scope["headers"] if k == _HEADER_NAME), None)
            # Cada requisição roda na sua própria task (uvicorn), então o valor não vaza para outra.
            bind_traceparent(raw.decode("latin-1") if raw is not None else None)
        await self._app(scope, receive, send)
