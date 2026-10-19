"""Entrypoint do Executor de Organization (`ipm-organization-executor`, decisões 0015 e 0063).

Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o consumer de `action`.
O Executor não acessa o SSOT; é o único com credencial de escrita no Zitadel.
"""

import asyncio
import logging

import httpx

from ipm_organization.common.http.health import Health, serve_health
from ipm_organization.common.lifecycle import start_role, stop_on_signals, supervise
from ipm_organization.common.messaging import JetStreamPublisher, connect, jetstream_of
from ipm_organization.executor.engine.executor import Executor
from ipm_organization.executor.provider.zitadel import ZitadelWriter
from ipm_organization.executor.settings import OrganizationExecutorSettings, missing_required
from ipm_organization.executor.transport.nats import ActionConsumer, DirectStateReader

logger = logging.getLogger(__name__)


async def run(settings: OrganizationExecutorSettings) -> int:
    stop = stop_on_signals()
    async with httpx.AsyncClient(timeout=settings.zitadel.timeout_seconds) as http:
        nats_client = await connect(settings.nats, name="ipm-organization-executor")
        jetstream = jetstream_of(nats_client)
        executor = Executor(
            ZitadelWriter(settings.zitadel, http),
            JetStreamPublisher(jetstream),
            DirectStateReader(jetstream),
        )
        health = Health()
        health.add_check("nats", lambda: nats_client.is_connected)
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
        logger.info("organization executor started")
        exit_code = await supervise(tasks, stop)
        await nats_client.drain()
    return exit_code


def main() -> None:
    start_role("executor", OrganizationExecutorSettings, missing_required, run)


if __name__ == "__main__":
    main()
