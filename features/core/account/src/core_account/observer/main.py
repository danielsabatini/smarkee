"""Entrypoint do Observer de Account (`core-account-observer`, decisões 0015 e 0063).

Só inicializa e encerra: valida a configuração, conecta ao NATS, cria os consumers de estado da
instância e roda a observação periódica. O Observer não acessa o SSOT e só lê o Zitadel.

Os logs do Observer não carregam o `traceparent` das mensagens que ele consome: a observação é
periódica e não consequência de uma requisição (`traced=False`, decisão 0055).
"""

import logging

import httpx

from core_account.common.lifecycle import start_role
from core_account.common.messaging import StateConsumer, StreamPublisher, new_instance_name
from core_account.common.runtime import role_runtime
from core_account.observer.engine.observer import Observer, periodic_observation
from core_account.observer.provider.identity import IdentityReader
from core_account.observer.settings import AccountObserverSettings, missing_required
from core_account.observer.transport.streams import STREAMS

logger = logging.getLogger(__name__)


async def run(settings: AccountObserverSettings) -> int:
    async with role_runtime(settings.messaging, name="core-account-observer") as runtime:
        http = httpx.AsyncClient(timeout=settings.identity.timeout_seconds)
        runtime.close_after(http.aclose)
        observer = Observer(
            IdentityReader(settings.identity, http), StreamPublisher(runtime.stream), settings
        )
        instance = new_instance_name()
        for stream, subject, suffix in STREAMS:
            runtime.start(
                suffix,
                StateConsumer(
                    runtime.stream,
                    observer,
                    durable=f"core-account-observer-{suffix}-{instance}",
                    stream=stream,
                    filter_subject=subject,
                    inactive_threshold_seconds=settings.messaging.consumer_inactive_threshold_seconds,
                    traced=False,
                    on_cycle=runtime.health.beat,
                ).run(runtime.stop),
            )
        runtime.start(
            "periodic",
            periodic_observation(observer, settings, runtime.stop, on_cycle=runtime.health.beat),
        )
        logger.info(
            "account observer started",
            extra={
                "smarkee.instance.name": instance,
                "smarkee.partition": f"{settings.partition.index}/{settings.partition.count}",
            },
        )
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role("observer", AccountObserverSettings, missing_required, run)


if __name__ == "__main__":
    main()
