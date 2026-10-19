"""Entrypoint do Manager de Account (`core-account-manager`, decisões 0015, 0019 e 0063).

Consome `requested`, `observed` e `completed`/`failed` e escreve no SSOT; só insere no outbox. A
publicação do outbox é do Publisher (`../publisher`). Só inicializa e encerra: valida a
configuração, abre as conexões e roda os consumers.
"""

import asyncio
import logging

from core_account.common.database import open_pool
from core_account.common.http.health import Health, serve_health
from core_account.common.lifecycle import start_role, stop_on_signals, supervise
from core_account.common.messaging import connect, stream_of
from core_account.manager.domain.kind import account_kind
from core_account.manager.handlers.observed import ObservedHandler
from core_account.manager.handlers.requested import RequestedHandler
from core_account.manager.handlers.result import ResultHandler
from core_account.manager.settings import AccountManagerSettings, missing_required
from core_account.manager.transport.consumers import (
    ObservedConsumer,
    RequestedConsumer,
    ResultConsumer,
)

logger = logging.getLogger(__name__)


async def run(settings: AccountManagerSettings) -> int:
    stop = stop_on_signals()
    health = Health()
    messaging_client = await connect(settings.messaging, name="core-account-manager")
    pool = await open_pool(settings.database)
    jetstream = stream_of(messaging_client)
    account = account_kind(settings.platform.roles)
    health.add_check("nats", lambda: messaging_client.is_connected)
    consumers = {
        "requested": RequestedConsumer(
            jetstream, pool, account, handler=RequestedHandler(), on_cycle=health.beat
        ),
        "observed": ObservedConsumer(
            jetstream, pool, account, handler=ObservedHandler(), on_cycle=health.beat
        ),
        "result": ResultConsumer(
            jetstream,
            pool,
            account,
            handler=ResultHandler(failure_limit=settings.loop.failure_limit),
            on_cycle=health.beat,
        ),
    }
    tasks = {name: asyncio.create_task(consumer.run(stop)) for name, consumer in consumers.items()}
    tasks["health"] = asyncio.create_task(serve_health(health, settings.health.port, stop))
    health.mark_started()
    logger.info("account manager started")
    exit_code = await supervise(tasks, stop)
    await messaging_client.drain()
    await pool.close()
    return exit_code


def main() -> None:
    start_role("manager", AccountManagerSettings, missing_required, run)


if __name__ == "__main__":
    main()
