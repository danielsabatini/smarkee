"""Entrypoint da API de Billing Account (`bsm-account-api`, decisões 0015, 0082, 0098 e 0100).

Valida a configuração, conecta ao banco e ao NATS e serve a API HTTP. As regras de admissão e
consulta ficam em `http/`, `domain/` e `store/`.
"""

import logging
import sys

import httpx

from bsm_account.api.auth.tokens import EmailVerification, TokenVerifier
from bsm_account.api.http.app import Dependencies, create_app
from bsm_account.api.settings import AccountApiSettings, missing_required
from bsm_account.api.store.admission import SsotAdmissionStore
from bsm_account.api.store.repository import SsotRepository
from bsm_account.api.transport.organization_usage_projection import (
    ORGANIZATION_SUBJECT,
    OrganizationUsageProjection,
)
from bsm_account.common.database import open_pool
from bsm_account.common.http.server import serve_http
from bsm_account.common.lifecycle import start_role
from bsm_account.common.messaging import StateConsumer, new_instance_name
from bsm_account.common.runtime import role_runtime

logger = logging.getLogger(__name__)


async def run(settings: AccountApiSettings) -> int:
    instance = new_instance_name()

    async with role_runtime(settings.messaging, name="bsm-account-api") as runtime:
        http = httpx.AsyncClient(timeout=5.0)
        runtime.close_after(http.aclose)
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)

        # Organizations que usam a Billing Account, sem consulta HTTP (0100).
        organizations = OrganizationUsageProjection()
        organization_consumer = StateConsumer(
            runtime.stream,
            organizations,
            durable=f"bsm-account-api-organizations-{instance}",
            stream="DESIRED",
            filter_subject=ORGANIZATION_SUBJECT,
            inactive_threshold_seconds=300,
            traced=False,
            on_cycle=runtime.health.beat,
        )
        runtime.start("organization-usage-projection", organization_consumer.run(runtime.stop))

        def is_synced() -> bool:
            return organization_consumer.is_synced

        app = create_app(
            Dependencies(
                settings=settings,
                authenticator=TokenVerifier(settings.auth, http),
                email_verifier=EmailVerification(settings.auth, http),
                repository=SsotRepository(pool),
                store=SsotAdmissionStore(pool),
                organizations=organizations,
                is_synced=is_synced,
            )
        )
        runtime.start(
            "http",
            serve_http(
                app,
                host=settings.api.host,
                port=settings.api.port,
                stop=runtime.stop,
            ),
        )
        logger.info(
            "account api started",
            extra={
                "smarkee.api.host": settings.api.host,
                "smarkee.api.port": settings.api.port,
            },
        )
        return await runtime.serve(health_port=None)


def main(argv: list[str] | None = None) -> None:
    start_role("api", AccountApiSettings, missing_required, run, cli_args=argv or sys.argv[1:])
