"""Entrypoint do Receiver de Organization (`ipm-organization-receiver`, decisão 0015).

Só inicializa e encerra: valida a configuração, abre as conexões e serve a aplicação HTTP. A
lógica fica nos módulos de cada responsabilidade.
"""

import asyncio
import logging
from collections.abc import Generator
from contextlib import contextmanager

import httpx
import uvicorn

from ipm_organization.common.database import open_pool
from ipm_organization.common.lifecycle import start_role, stop_on_signals, supervise
from ipm_organization.common.messaging import StreamPublisher, connect, stream_of
from ipm_organization.receiver.auth.tokens import EmailVerification, TokenVerifier
from ipm_organization.receiver.http.app import Dependencies, create_app
from ipm_organization.receiver.settings import OrganizationReceiverSettings, missing_required
from ipm_organization.receiver.store.repository import SsotRepository

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


async def run(settings: OrganizationReceiverSettings) -> int:
    stop = stop_on_signals()
    async with httpx.AsyncClient(timeout=5.0) as http:
        messaging_client = await connect(settings.nats, name="ipm-organization-receiver")
        pool = await open_pool(settings.database)
        api = settings.api
        server = _Server(
            uvicorn.Config(
                create_app(
                    Dependencies(
                        settings=api,
                        authenticator=TokenVerifier(settings.auth, http),
                        email_verifier=EmailVerification(settings.auth, http),
                        is_ready=lambda: messaging_client.is_connected,
                        repository=SsotRepository(pool),
                        publisher=StreamPublisher(stream_of(messaging_client)),
                    )
                ),
                host=api.host,
                port=api.port,
                log_config=None,
                access_log=False,
            )
        )
        tasks = {"http": asyncio.create_task(_serve_until_stopped(server, stop))}
        logger.info("organization api started")
        exit_code = await supervise(tasks, stop)
        await messaging_client.drain()
        await pool.close()
    return exit_code


def main() -> None:
    start_role("receiver", OrganizationReceiverSettings, missing_required, run)


if __name__ == "__main__":
    main()
