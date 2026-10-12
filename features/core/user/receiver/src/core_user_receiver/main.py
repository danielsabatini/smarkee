"""Entrypoint do Receiver de User (`core-user-receiver`, decisão 0015).

Só inicializa e encerra: valida a configuração, abre as conexões e serve a aplicação HTTP. A
lógica fica nos módulos de cada responsabilidade.
"""

import asyncio
import contextlib
import logging
import signal
import sys

import httpx
import uvicorn

from core_user_receiver.auth.tokens import TokenVerifier
from core_user_receiver.domain.ratelimit import SlidingWindowLimiter
from core_user_receiver.http.app import Dependencies, create_app
from core_user_receiver.logging_config import configure_logging
from core_user_receiver.settings import UserReceiverSettings, missing_required
from core_user_receiver.store.database import open_pool
from core_user_receiver.store.repository import PostgresRepository
from core_user_receiver.transport.nats import JetStreamPublisher, connect, jetstream_of

EXIT_INVALID_CONFIGURATION = 2

logger = logging.getLogger(__name__)


async def run(settings: UserReceiverSettings) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop.set)

    async with httpx.AsyncClient(timeout=5.0) as http:
        nats_client = await connect(settings.nats)
        pool = await open_pool(settings.database)
        api = settings.api
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(
                    Dependencies(
                        settings=api,
                        authenticator=TokenVerifier(settings.auth, http),
                        repository=PostgresRepository(pool),
                        publisher=JetStreamPublisher(jetstream_of(nats_client)),
                        is_ready=lambda: nats_client.is_connected,
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
        # O encerramento é conduzido por este módulo; o uvicorn não instala os seus handlers.
        server.install_signal_handlers = lambda: contextlib.nullcontext()  # type: ignore[method-assign]

        serving = asyncio.create_task(server.serve())
        logger.info("user api started")
        waiter = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait({waiter, serving}, return_when=asyncio.FIRST_COMPLETED)

        exit_code = 1 if serving in done else 0
        if exit_code:
            logger.error("http server stopped unexpectedly")
        server.should_exit = True
        stop.set()
        result = (await asyncio.gather(serving, return_exceptions=True))[0]
        if isinstance(result, BaseException):
            logger.error("http server failed", extra={"error_type": type(result).__name__})
            exit_code = 1
        waiter.cancel()
        await nats_client.drain()
        await pool.close()
    return exit_code


def main() -> None:
    configure_logging()
    settings = UserReceiverSettings()
    missing = missing_required(settings)
    if missing:
        logger.error("missing required configuration", extra={"variables": missing})
        sys.exit(EXIT_INVALID_CONFIGURATION)
    sys.exit(asyncio.run(run(settings)))


if __name__ == "__main__":
    main()
