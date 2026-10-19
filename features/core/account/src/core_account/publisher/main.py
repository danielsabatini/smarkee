"""Entrypoint do Publisher de Account (`core-account-publisher`, decisões 0015, 0019 e 0063).

Lê o outbox do tipo e publica no transporte, em ordem; uma instância ativa por trava consultiva.
Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o Publisher.
"""

import asyncio
import logging

from core_account.common.http.health import Health, serve_health
from core_account.common.lifecycle import start_role, stop_on_signals, supervise
from core_account.common.messaging import StreamPublisher, connect, stream_of
from core_account.publisher.outbox.publication import OutboxPublisher
from core_account.publisher.settings import AccountPublisherSettings, missing_required

logger = logging.getLogger(__name__)


async def run(settings: AccountPublisherSettings) -> int:
    stop = stop_on_signals()
    health = Health()
    messaging_client = await connect(settings.nats, name="core-account-publisher")
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
    logger.info("account publisher started")
    exit_code = await supervise(tasks, stop)
    await messaging_client.drain()
    return exit_code


def main() -> None:
    start_role("publisher", AccountPublisherSettings, missing_required, run)


if __name__ == "__main__":
    main()
