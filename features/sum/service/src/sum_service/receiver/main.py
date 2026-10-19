"""Entrypoint do Receiver de `sum.service` (`sum-service-receiver`, decisões 0015 e 0033).

Autentica o solicitante, confere a role da ação, publica o `requested` e responde. Só inicializa e
encerra:
valida a configuração, abre as conexões e serve a API.
"""

import logging

import httpx
import uvicorn
from psycopg.rows import dict_row

from sum_service.common.database import open_pool
from sum_service.common.http.health import Health
from sum_service.common.lifecycle import start_role
from sum_service.common.messaging import connect, jetstream_of
from sum_service.receiver.auth.tokens import TokenVerifier
from sum_service.receiver.http.app import Dependencies, create_app
from sum_service.receiver.settings import SumServiceReceiverSettings, missing_required
from sum_service.receiver.store.repository import Repository
from sum_service.receiver.transport.dependents import PeerDependents
from sum_service.receiver.transport.nats import RequestedPublisher

logger = logging.getLogger(__name__)


async def serve(settings: SumServiceReceiverSettings) -> int:
    health = Health()
    nats_client = await connect(settings.nats, name="sum-service-receiver")
    pool = await open_pool(settings.database, row_factory=dict_row)
    health.add_check("nats", lambda: nats_client.is_connected)
    async with httpx.AsyncClient(timeout=5.0) as client:
        app = create_app(
            Dependencies(
                verifier=TokenVerifier(settings.auth, client),
                repository=Repository(pool),
                publisher=RequestedPublisher(jetstream_of(nats_client)),
                health=health,
                dependents=PeerDependents(settings.peers, client),
            )
        )
        health.mark_started()
        logger.info("sum service receiver started")
        config = uvicorn.Config(
            app, host=settings.api.host, port=settings.api.port, log_config=None
        )
        await uvicorn.Server(config).serve()
    await nats_client.drain()
    await pool.close()
    return 0


def main() -> None:
    start_role("receiver", SumServiceReceiverSettings, missing_required, serve)


if __name__ == "__main__":
    main()
