"""Servidor HTTP do Receiver (uvicorn) sob o ciclo de vida comum (`common/runtime.py`).

O uvicorn instala os próprios handlers de sinal e encerra o processo por conta própria; aqui eles
são desligados, e o servidor para quando o pedido de parada do papel (`stop`) é dado. Assim o
Receiver encerra como os demais papéis: drena o broker e fecha o banco depois de parar de aceitar
requisições.
"""

import asyncio
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import uvicorn


class _Server(uvicorn.Server):
    """Servidor sem os handlers de sinal do uvicorn: o encerramento é conduzido pelo papel."""

    @contextmanager
    def capture_signals(self) -> Generator[None]:
        yield


async def serve_http(app: Any, *, host: str, port: int, stop: asyncio.Event) -> None:
    """Serve `app` até `stop`; os logs de acesso ficam desligados (a borda os registra)."""
    server = _Server(uvicorn.Config(app, host=host, port=port, log_config=None, access_log=False))

    async def request_exit() -> None:
        await stop.wait()
        server.should_exit = True

    watcher = asyncio.create_task(request_exit())
    try:
        await server.serve()
    finally:
        watcher.cancel()
