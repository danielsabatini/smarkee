"""Entrypoint do serviço `core` (decisão 0011).

Um processo, formato colapsado (`docs/RESOURCE-CONTROL-LOOP.md` §48): a API HTTP e os workers
(consumers do Manager e relays do outbox) rodam como tarefas `asyncio`. Este módulo só inicializa
e encerra; a lógica fica nos módulos de cada responsabilidade.
"""

import asyncio
import contextlib
import logging
import signal
import sys

import httpx
import uvicorn

from core.api.app import Dependencies, create_app
from core.api.auth import EmailVerification, TokenVerifier
from core.api.ratelimit import SlidingWindowLimiter
from core.api.repository import PostgresRepository
from core.database import open_pool
from core.logging_config import configure_logging
from core.manager.kinds import ORGANIZATION, USER
from core.messaging.jetstream import (
    JetStreamPublisher,
    RequestedConsumer,
    connect,
    jetstream_of,
)
from core.relay import OutboxRelay
from core.settings import CoreSettings, missing_required

EXIT_INVALID_CONFIGURATION = 2

logger = logging.getLogger(__name__)


async def run(settings: CoreSettings) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop.set)

    async with httpx.AsyncClient(timeout=5.0) as http:
        nats_client = await connect(settings.nats)
        jetstream = jetstream_of(nats_client)
        publisher = JetStreamPublisher(jetstream)
        pools = {
            role: await open_pool(settings.database, role)
            for role in ("organization_manager", "organization_api", "user_manager", "user_api")
        }
        api = settings.api
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(
                    Dependencies(
                        settings=api,
                        authenticator=TokenVerifier(settings.auth, http),
                        email_verifier=EmailVerification(settings.auth, http),
                        repository=PostgresRepository(
                            {"organization": pools["organization_api"], "user": pools["user_api"]}
                        ),
                        publisher=publisher,
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

        workers = {
            "api": asyncio.create_task(server.serve()),
            "manager-organization": asyncio.create_task(
                RequestedConsumer(jetstream, pools["organization_manager"], ORGANIZATION).run(stop)
            ),
            "manager-user": asyncio.create_task(
                RequestedConsumer(jetstream, pools["user_manager"], USER).run(stop)
            ),
            "relay-organization": asyncio.create_task(
                OutboxRelay(settings.database, ORGANIZATION, publisher).run(stop)
            ),
            "relay-user": asyncio.create_task(
                OutboxRelay(settings.database, USER, publisher).run(stop)
            ),
        }
        logger.info("core service started", extra={"workers": sorted(workers)})
        waiter = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait(
            {waiter, *workers.values()}, return_when=asyncio.FIRST_COMPLETED
        )

        exit_code = 0
        for name, task in workers.items():
            if task in done:
                exit_code = 1
                logger.error("worker stopped unexpectedly", extra={"worker": name})
        stop.set()
        server.should_exit = True
        results = await asyncio.gather(*workers.values(), return_exceptions=True)
        for name, result in zip(workers, results, strict=True):
            if isinstance(result, BaseException):
                logger.error(
                    "worker failed", extra={"worker": name, "error_type": type(result).__name__}
                )
                exit_code = 1
        waiter.cancel()
        await nats_client.drain()
        for pool in pools.values():
            await pool.close()
    return exit_code


def main() -> None:
    configure_logging()
    settings = CoreSettings()
    missing = missing_required(settings)
    if missing:
        logger.error("missing required configuration", extra={"variables": missing})
        sys.exit(EXIT_INVALID_CONFIGURATION)
    sys.exit(asyncio.run(run(settings)))


if __name__ == "__main__":
    main()
