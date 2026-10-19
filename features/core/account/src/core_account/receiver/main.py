"""Entrypoint do Receiver de Account (`core-account-receiver`, decisão 0015).

Só inicializa e encerra: valida a configuração, abre as conexões e serve a aplicação HTTP. A
lógica fica nos módulos de cada responsabilidade.
"""

import asyncio
import logging
from collections.abc import Generator
from contextlib import contextmanager

import httpx
import uvicorn

from core_account.common.database import open_pool
from core_account.common.lifecycle import start_role, stop_on_signals, supervise
from core_account.common.messaging import StreamPublisher, connect, stream_of
from core_account.receiver.auth.tokens import TokenVerifier
from core_account.receiver.domain.ratelimit import SlidingWindowLimiter
from core_account.receiver.http.app import Dependencies, create_app
from core_account.receiver.settings import AccountReceiverSettings, missing_required
from core_account.receiver.store.repository import SsotRepository
from core_account.receiver.transport.peers import PeerResources

logger = logging.getLogger(__name__)


class _Server(uvicorn.Server):
    """Servidor sem os handlers de sinal do uvicorn: o encerramento é conduzido por `lifecycle`."""

    @contextmanager
    def capture_signals(self) -> Generator[None]:
        yield


async def _serve_until_stopped(server: _Server, stop: asyncio.Event) -> None:
    async def request_exit() -> None:
        await stop.wait()
        server.should_exit = True

    watcher = asyncio.create_task(request_exit())
    try:
        await server.serve()
    finally:
        watcher.cancel()


async def run(settings: AccountReceiverSettings) -> int:
    stop = stop_on_signals()
    async with httpx.AsyncClient(timeout=5.0) as http:
        messaging_client = await connect(settings.messaging, name="core-account-receiver")
        pool = await open_pool(settings.database)
        api = settings.api
        server = _Server(
            uvicorn.Config(
                create_app(
                    Dependencies(
                        settings=api,
                        authenticator=TokenVerifier(settings.auth, http),
                        repository=SsotRepository(pool),
                        publisher=StreamPublisher(stream_of(messaging_client)),
                        resources=PeerResources(settings.peers, http),
                        is_ready=lambda: messaging_client.is_connected,
                        limiter=SlidingWindowLimiter(
                            api.anonymous_rate_limit, api.anonymous_rate_window_seconds
                        ),
                    )
                ),
                host=api.host,
                port=api.port,
                log_config=None,
                access_log=False,
            )
        )
        tasks = {"http": asyncio.create_task(_serve_until_stopped(server, stop))}
        logger.info("account api started")
        exit_code = await supervise(tasks, stop)
        await messaging_client.drain()
        await pool.close()
    return exit_code


def main() -> None:
    start_role("receiver", AccountReceiverSettings, missing_required, run)


if __name__ == "__main__":
    main()
