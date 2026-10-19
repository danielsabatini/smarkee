"""Entrypoint do Observer de Account (`core-account-observer`, decisões 0015 e 0063).

Só inicializa e encerra: valida a configuração, conecta ao NATS, cria os consumers de estado da
instância e roda a observação periódica. O Observer não acessa o SSOT e só lê o Zitadel.

Os logs do Observer não carregam o `traceparent` das mensagens que ele consome: a observação é
periódica e não consequência de uma requisição (`traced=False`, decisão 0055).
"""

import asyncio
import logging

import httpx

from core_account.common.http.health import Health, serve_health
from core_account.common.lifecycle import start_role, stop_on_signals, supervise
from core_account.common.messaging import (
    StateConsumer,
    StreamPublisher,
    connect,
    new_instance_name,
    stream_of,
)
from core_account.observer.engine.observer import Observer, periodic_observation
from core_account.observer.provider.identity import IdentityReader
from core_account.observer.settings import AccountObserverSettings, missing_required
from core_account.observer.transport.streams import STREAMS

logger = logging.getLogger(__name__)


async def run(settings: AccountObserverSettings) -> int:
    stop = stop_on_signals()
    async with httpx.AsyncClient(timeout=settings.identity.timeout_seconds) as http:
        messaging_client = await connect(settings.messaging, name="core-account-observer")
        health = Health()
        health.add_check("nats", lambda: messaging_client.is_connected)
        jetstream = stream_of(messaging_client)
        observer = Observer(
            IdentityReader(settings.identity, http), StreamPublisher(jetstream), settings
        )
        instance = new_instance_name()
        tasks = {
            suffix: asyncio.create_task(
                StateConsumer(
                    jetstream,
                    observer,
                    durable=f"core-account-observer-{suffix}-{instance}",
                    stream=stream,
                    filter_subject=subject,
                    inactive_threshold_seconds=settings.messaging.consumer_inactive_threshold_seconds,
                    traced=False,
                    on_cycle=health.beat,
                ).run(stop)
            )
            for stream, subject, suffix in STREAMS
        }
        tasks["periodic"] = asyncio.create_task(
            periodic_observation(observer, settings, stop, on_cycle=health.beat)
        )
        tasks["health"] = asyncio.create_task(serve_health(health, settings.health.port, stop))
        health.mark_started()
        logger.info(
            "account observer started",
            extra={
                "smarkee.instance.name": instance,
                "smarkee.partition": f"{settings.partition.index}/{settings.partition.count}",
            },
        )
        exit_code = await supervise(tasks, stop)
        await messaging_client.drain()
    return exit_code


def main() -> None:
    start_role("observer", AccountObserverSettings, missing_required, run)


if __name__ == "__main__":
    main()
