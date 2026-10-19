"""Entrypoint do Executor de Account (`core-account-executor`, decisões 0015 e 0063).

Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o consumer de `action`.
O Executor não acessa o SSOT; é o único com credencial de escrita no Zitadel.
"""

import asyncio
import logging

import httpx

from core_account.common.http.health import Health, serve_health
from core_account.common.lifecycle import start_role, stop_on_signals, supervise
from core_account.common.messaging import StreamPublisher, connect, stream_of
from core_account.executor.engine.executor import Executor
from core_account.executor.provider.identity import IdentityWriter
from core_account.executor.settings import AccountExecutorSettings, missing_required
from core_account.executor.transport.messaging import ActionConsumer, DirectStateReader

logger = logging.getLogger(__name__)


async def run(settings: AccountExecutorSettings) -> int:
    stop = stop_on_signals()
    async with httpx.AsyncClient(timeout=settings.zitadel.timeout_seconds) as http:
        messaging_client = await connect(settings.nats, name="core-account-executor")
        jetstream = stream_of(messaging_client)
        executor = Executor(
            IdentityWriter(settings.zitadel, http),
            StreamPublisher(jetstream),
            DirectStateReader(jetstream),
        )
        health = Health()
        health.add_check("nats", lambda: messaging_client.is_connected)
        tasks = {
            f"action-p{partition}": asyncio.create_task(
                ActionConsumer(jetstream, executor, partition=partition, on_cycle=health.beat).run(
                    stop
                )
            )
            for partition in range(settings.partition.count)
        }
        tasks["health"] = asyncio.create_task(serve_health(health, settings.health.port, stop))
        health.mark_started()
        logger.info("account executor started")
        exit_code = await supervise(tasks, stop)
        await messaging_client.drain()
    return exit_code


def main() -> None:
    start_role("executor", AccountExecutorSettings, missing_required, run)


if __name__ == "__main__":
    main()
