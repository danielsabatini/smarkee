"""Entrypoint da API de `sum.service` (`sum-service-api`, decisões 0015, 0033, 0098 e 0100).

Valida a configuração (inclusive o catálogo de serviços), conecta ao banco e ao NATS e serve a API
HTTP. As regras de admissão e consulta ficam em `http/`, `domain/` e `store/`.
"""

import logging
import sys

import httpx

from sum_service.api.auth.tokens import TokenVerifier
from sum_service.api.http.app import Dependencies, create_app
from sum_service.api.settings import SumServiceApiSettings, missing_required
from sum_service.api.store.admission import SsotAdmissionStore
from sum_service.api.store.repository import SsotRepository
from sum_service.api.transport.attached_projection import (
    BILLING_ACCOUNTS,
    ORGANIZATIONS,
    AttachedProjection,
    AttachedResources,
)
from sum_service.common.database import open_pool
from sum_service.common.http.server import serve_http
from sum_service.common.lifecycle import InvalidConfigurationError, start_role
from sum_service.common.messaging import StateConsumer, new_instance_name
from sum_service.common.runtime import role_runtime
from sum_service.common.service_rules import CatalogError, parse_catalog

logger = logging.getLogger(__name__)


async def run(settings: SumServiceApiSettings) -> int:
    catalog = parse_catalog(settings.catalog.permissions or "")
    instance = new_instance_name()

    async with role_runtime(settings.messaging, name="sum-service-api") as runtime:
        http = httpx.AsyncClient(timeout=5.0)
        runtime.close_after(http.aclose)
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)

        # Recursos de outros módulos do dono, sem consulta HTTP (decisão 0100).
        consumers: list[StateConsumer] = []
        projections: dict[str, AttachedProjection] = {}
        for kind in (ORGANIZATIONS, BILLING_ACCOUNTS):
            projection = AttachedProjection(kind)
            consumer = StateConsumer(
                runtime.stream,
                projection,
                durable=f"sum-service-api-{kind.module}-{kind.resource_type}-{instance}",
                stream="DESIRED",
                filter_subject=kind.subject,
                inactive_threshold_seconds=300,
                traced=False,
                on_cycle=runtime.health.beat,
            )
            runtime.start(
                f"{kind.module}-{kind.resource_type}-projection", consumer.run(runtime.stop)
            )
            projections[kind.module] = projection
            consumers.append(consumer)

        api = settings.api
        app = create_app(
            Dependencies(
                authenticator=TokenVerifier(settings.auth, http),
                repository=SsotRepository(pool),
                admissions=SsotAdmissionStore(pool),
                attachments=AttachedResources(
                    projections["ipm"],
                    projections["bsm"],
                    lambda: all(consumer.is_synced for consumer in consumers),
                ),
                catalog=catalog,
                is_ready=lambda: runtime.client.is_connected,
            )
        )
        runtime.start("http", serve_http(app, host=api.host, port=api.port, stop=runtime.stop))
        logger.info(
            "service api started",
            extra={"smarkee.api.host": api.host, "smarkee.api.port": api.port},
        )
        # As probes são rotas da própria aplicação HTTP (`http/health_routes.py`).
        return await runtime.serve(health_port=None)


def validate(settings: SumServiceApiSettings) -> None:
    try:
        parse_catalog(settings.catalog.permissions or "")
    except CatalogError as error:
        raise InvalidConfigurationError(f"invalid service catalog: {error}") from None


def main(argv: list[str] | None = None) -> None:
    start_role(
        "api",
        SumServiceApiSettings,
        missing_required,
        run,
        validate=validate,
        cli_args=argv or sys.argv[1:],
    )


if __name__ == "__main__":
    main()
