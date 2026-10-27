"""Entrypoint da API de Account (`core-account-api`, decisões 0015, 0098 e 0100).

Valida a configuração, conecta ao banco e ao NATS e serve a API HTTP. As regras de admissão e
consulta ficam em `http/`, `domain/` e `store/`.
"""

import logging
import sys

import httpx

from core_account.api.auth.tokens import TokenVerifier
from core_account.api.domain.ratelimit import SlidingWindowLimiter
from core_account.api.http.app import Dependencies, create_app
from core_account.api.settings import AccountApiSettings, missing_required
from core_account.api.store.admission import SsotAdmissionStore
from core_account.api.store.repository import SsotRepository
from core_account.api.transport.attached_projection import (
    BILLING_ACCOUNTS,
    ORGANIZATIONS,
    SERVICES,
    AttachedProjection,
    AttachedResources,
)
from core_account.common.database import open_pool
from core_account.common.http.server import serve_http
from core_account.common.lifecycle import start_role
from core_account.common.messaging import StateConsumer, new_instance_name
from core_account.common.runtime import role_runtime

logger = logging.getLogger(__name__)


async def run(settings: AccountApiSettings) -> int:
    instance = new_instance_name()

    async with role_runtime(settings.messaging, name="core-account-api") as runtime:
        http = httpx.AsyncClient(timeout=5.0)
        runtime.close_after(http.aclose)
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)

        # Recursos de outros módulos atrelados à conta, sem consulta HTTP (0100).
        consumers: list[StateConsumer] = []
        projections: list[AttachedProjection] = []
        for kind in (ORGANIZATIONS, BILLING_ACCOUNTS, SERVICES):
            projection = AttachedProjection(kind)
            consumer = StateConsumer(
                runtime.stream,
                projection,
                durable=f"core-account-api-{kind.module}-{kind.resource_type}-{instance}",
                stream="DESIRED",
                filter_subject=kind.subject,
                inactive_threshold_seconds=300,
                traced=False,
                on_cycle=runtime.health.beat,
            )
            runtime.start(
                f"{kind.module}-{kind.resource_type}-projection", consumer.run(runtime.stop)
            )
            projections.append(projection)
            consumers.append(consumer)

        def are_attachments_synced() -> bool:
            return all(consumer.is_synced for consumer in consumers)

        api = settings.api
        app = create_app(
            Dependencies(
                settings=settings,
                authenticator=TokenVerifier(settings.auth, http),
                repository=SsotRepository(pool),
                admissions=SsotAdmissionStore(pool),
                attachments=AttachedResources(projections),
                limiter=SlidingWindowLimiter(
                    api.anonymous_rate_limit, api.anonymous_rate_window_seconds
                ),
                are_attachments_synced=are_attachments_synced,
                is_ready=lambda: runtime.client.is_connected,
            )
        )
        runtime.start("http", serve_http(app, host=api.host, port=api.port, stop=runtime.stop))
        logger.info(
            "account api started",
            extra={"smarkee.api.host": api.host, "smarkee.api.port": api.port},
        )
        # As probes são rotas da própria aplicação HTTP (`http/health_routes.py`).
        return await runtime.serve(health_port=None)


def main(argv: list[str] | None = None) -> None:
    start_role("api", AccountApiSettings, missing_required, run, cli_args=argv or sys.argv[1:])


if __name__ == "__main__":
    main()
