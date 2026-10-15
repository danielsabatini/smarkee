"""Entrypoint do Receiver de `sum.service` (`sum-service-receiver`, decisões 0015 e 0033).

Autentica o solicitante, confere a role da ação, publica o `requested` e responde. Só inicializa e
encerra:
valida a configuração, abre as conexões e serve a API.
"""

import asyncio
import logging
import sys

import httpx
import uvicorn

from sum_service_receiver.auth.tokens import TokenVerifier
from sum_service_receiver.database import open_pool
from sum_service_receiver.http.app import Dependencies, create_app
from sum_service_receiver.http.health import Health
from sum_service_receiver.logging_config import configure_logging
from sum_service_receiver.settings import SumServiceReceiverSettings, missing_required
from sum_service_receiver.store.repository import Repository
from sum_service_receiver.transport.nats import RequestedPublisher, connect, jetstream_of

EXIT_INVALID_CONFIGURATION = 2

logger = logging.getLogger(__name__)


async def serve(settings: SumServiceReceiverSettings) -> int:
    health = Health()
    nats_client = await connect(settings.nats.url, settings.nats.user, settings.nats.password)
    pool = await open_pool(settings.database)
    health.add_check("nats", lambda: nats_client.is_connected)
    async with httpx.AsyncClient(timeout=5.0) as client:
        app = create_app(
            Dependencies(
                verifier=TokenVerifier(settings.auth, client),
                repository=Repository(pool),
                publisher=RequestedPublisher(jetstream_of(nats_client)),
                health=health,
            )
        )
        health.mark_started()
        logger.info("sum service receiver started")
        config = uvicorn.Config(
            app, host=settings.api.host, port=settings.api.port, log_config=None
        )
        await uvicorn.Server(config).serve()
    await nats_client.close()
    await pool.close()
    return 0


def main() -> None:
    configure_logging()
    settings = SumServiceReceiverSettings()
    missing = missing_required(settings)
    if missing:
        logger.error("missing required configuration", extra={"variables": missing})
        sys.exit(EXIT_INVALID_CONFIGURATION)
    sys.exit(asyncio.run(serve(settings)))


if __name__ == "__main__":
    main()
