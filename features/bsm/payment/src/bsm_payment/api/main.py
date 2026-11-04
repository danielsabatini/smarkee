"""Entrypoint da API de Payment (`bsm-payment-api`, decisões 0015, 0098 e 0100).

Valida a configuração, conecta ao banco e ao NATS e serve a API HTTP. As regras de admissão e
consulta ficam em `http/`, `domain/` e `store/`.
"""

import logging
import sys

import httpx

from bsm_payment.api.auth.tokens import EmailVerification, TokenVerifier
from bsm_payment.api.http.app import Dependencies, create_app
from bsm_payment.api.settings import PaymentApiSettings, missing_required
from bsm_payment.api.store.admission import SsotAdmissionStore
from bsm_payment.api.store.repository import SsotRepository
from bsm_payment.api.transport.billing_account_usage_projection import (
    BILLING_ACCOUNT_SUBJECT,
    BillingAccountUsageProjection,
)
from bsm_payment.common.database import open_pool
from bsm_payment.common.http.server import serve_http
from bsm_payment.common.lifecycle import start_role
from bsm_payment.common.messaging import StateConsumer, new_instance_name
from bsm_payment.common.runtime import role_runtime

logger = logging.getLogger(__name__)


async def run(settings: PaymentApiSettings) -> int:
    instance = new_instance_name()
    async with (
        role_runtime(settings.messaging, name=f"bsm-payment-api-{instance}") as runtime,
        httpx.AsyncClient(timeout=settings.auth.http_timeout_seconds) as auth_client,
    ):
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)

        billing_accounts = BillingAccountUsageProjection()
        billing_account_consumer = StateConsumer(
            runtime.stream,
            billing_accounts,
            durable=f"bsm-payment-api-accounts-{instance}",
            stream="DESIRED",
            filter_subject=BILLING_ACCOUNT_SUBJECT,
            inactive_threshold_seconds=300,
            traced=False,
            on_cycle=runtime.health.beat,
        )
        runtime.start("billing-accounts", billing_account_consumer.run(runtime.stop))

        app = create_app(
            Dependencies(
                settings=settings,
                authenticator=TokenVerifier(settings.auth, auth_client),
                email_verifier=EmailVerification(settings.auth, auth_client),
                repository=SsotRepository(pool),
                store=SsotAdmissionStore(pool),
                billing_accounts=billing_accounts,
                is_synced=lambda: (
                    runtime.client.is_connected and billing_account_consumer.is_synced
                ),
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
        logger.info("payment api started", extra={"smarkee.http.port": settings.api.port})
        return await runtime.serve(health_port=None)


def main() -> None:
    start_role("api", PaymentApiSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
