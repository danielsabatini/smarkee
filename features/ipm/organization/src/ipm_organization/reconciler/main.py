"""Entrypoint do Reconciler de Organization (`ipm-organization-reconciler`, decisões 0015 e 0063).

Só inicializa e encerra: valida a configuração, conecta ao NATS, cria os consumers de estado da
instância e roda a reavaliação periódica. O Reconciler não acessa o SSOT.
"""

import asyncio
import logging

from ipm_organization.common.http.health import Health, serve_health
from ipm_organization.common.lifecycle import start_role, stop_on_signals, supervise
from ipm_organization.common.messaging import (
    StateConsumer,
    StreamPublisher,
    connect,
    new_instance_name,
    stream_of,
)
from ipm_organization.reconciler.engine.reconciler import Reconciler, periodic_reevaluation
from ipm_organization.reconciler.settings import OrganizationReconcilerSettings, missing_required
from ipm_organization.reconciler.transport.streams import STREAMS

logger = logging.getLogger(__name__)


async def run(settings: OrganizationReconcilerSettings) -> int:
    stop = stop_on_signals()
    messaging_client = await connect(settings.nats, name="ipm-organization-reconciler")
    jetstream = stream_of(messaging_client)
    health = Health()
    health.add_check("nats", lambda: messaging_client.is_connected)
    reconciler = Reconciler(StreamPublisher(jetstream), settings.loop)
    instance = new_instance_name()
    tasks = {
        suffix: asyncio.create_task(
            StateConsumer(
                jetstream,
                reconciler,
                durable=f"ipm-organization-reconciler-{suffix}-{instance}",
                stream=stream,
                filter_subject=subject,
                inactive_threshold_seconds=settings.nats.consumer_inactive_threshold_seconds,
                traced=True,
                on_cycle=health.beat,
            ).run(stop)
        )
        for stream, subject, suffix in STREAMS
    }
    tasks["periodic"] = asyncio.create_task(
        periodic_reevaluation(reconciler, settings.loop, stop, on_cycle=health.beat)
    )
    tasks["health"] = asyncio.create_task(serve_health(health, settings.health.port, stop))
    health.mark_started()
    logger.info("organization reconciler started", extra={"smarkee.instance.name": instance})
    exit_code = await supervise(tasks, stop)
    await messaging_client.drain()
    return exit_code


def main() -> None:
    start_role("reconciler", OrganizationReconcilerSettings, missing_required, run)


if __name__ == "__main__":
    main()
