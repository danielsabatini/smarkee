"""Entrypoint do Publisher de `sum.service` (decisões 0015 e 0033).

Contêiner `sum-service-publisher`.
Lê o outbox do tipo e publica no transporte, em ordem; uma instância ativa por trava consultiva.
Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o Publisher. Uma recusa
permanente não derruba o processo: o Publisher sai de `ready` e quem opera é avisado (decisão 0018).
"""

import asyncio
import logging

from sum_service.common.http.health import Health, serve_health
from sum_service.common.lifecycle import start_role, stop_on_signals, supervise
from sum_service.common.messaging import StreamPublisher, connect, stream_of
from sum_service.publisher.outbox.publication import OutboxPublisher
from sum_service.publisher.settings import SumServicePublisherSettings, missing_required

logger = logging.getLogger(__name__)


async def run(settings: SumServicePublisherSettings) -> int:
    stop = stop_on_signals()
    health = Health()
    messaging_client = await connect(settings.messaging, name="sum-service-publisher")
    publisher = OutboxPublisher(
        settings.database, StreamPublisher(stream_of(messaging_client)), on_cycle=health.beat
    )
    health.add_check("nats", lambda: messaging_client.is_connected)
    health.add_check("publication", lambda: not publisher.blocked_by_permanent_failure)
    tasks = {
        "publisher": asyncio.create_task(publisher.run(stop)),
        "health": asyncio.create_task(serve_health(health, settings.health.port, stop)),
    }
    health.mark_started()
    logger.info("sum service publisher started")
    exit_code = await supervise(tasks, stop)
    await messaging_client.drain()
    return exit_code


def main() -> None:
    start_role("publisher", SumServicePublisherSettings, missing_required, run)


if __name__ == "__main__":
    main()
