"""Entrypoint da API de User (`ipm-user-api`, decisões 0015 e 0098).

Só inicializa e encerra: valida a configuração, abre as conexões e serve a aplicação HTTP. A
lógica fica nos módulos de cada responsabilidade.
"""

import logging
import sys

import httpx

from ipm_user.api.auth.tokens import TokenVerifier
from ipm_user.api.http.app import Dependencies, create_app
from ipm_user.api.settings import UserApiSettings, missing_required
from ipm_user.api.store.admission import SsotAdmissionStore
from ipm_user.api.store.repository import SsotRepository
from ipm_user.api.transport.catalog_consumer import CatalogWatcher
from ipm_user.api.transport.member_projection import (
    SERVICEACCOUNT_SUBJECT,
    USER_SUBJECT,
    MemberProjection,
)
from ipm_user.api.transport.organization_projection import (
    ORGANIZATION_SUBJECT,
    OrganizationProjection,
)
from ipm_user.common.catalog import AccessCatalog
from ipm_user.common.database import open_pool
from ipm_user.common.http.server import serve_http
from ipm_user.common.lifecycle import start_role
from ipm_user.common.messaging import StateConsumer, new_instance_name
from ipm_user.common.runtime import role_runtime

logger = logging.getLogger(__name__)


async def run(settings: UserApiSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-user-api") as runtime:
        http = httpx.AsyncClient(timeout=5.0)
        runtime.close_after(http.aclose)
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)
        api = settings.api
        catalog = AccessCatalog()
        watcher = CatalogWatcher(catalog)
        instance = new_instance_name()
        catalog_consumers: dict[str, StateConsumer] = {}
        for suffix, subject in (
            ("permissions", "desired.ipm.permission.>"),
            ("roles", "desired.ipm.role.>"),
            ("groups", "desired.ipm.group.>"),
        ):
            consumer = StateConsumer(
                runtime.stream,
                watcher,
                durable=f"ipm-user-api-{suffix}-{instance}",
                stream="DESIRED",
                filter_subject=subject,
                inactive_threshold_seconds=300,
                traced=False,
                on_cycle=runtime.health.beat,
            )
            catalog_consumers[suffix] = consumer
            runtime.start(suffix, consumer.run(runtime.stop))

        # Dono e ciclo de vida das Organizations, sem consulta à API da Organization (0100).
        organizations = OrganizationProjection()
        organization_consumer = StateConsumer(
            runtime.stream,
            organizations,
            durable=f"ipm-user-api-organizations-{instance}",
            stream="DESIRED",
            filter_subject=ORGANIZATION_SUBJECT,
            inactive_threshold_seconds=300,
            traced=False,
            on_cycle=runtime.health.beat,
        )
        runtime.start("organization-projection", organization_consumer.run(runtime.stop))

        # Organization dos membros (usuários e service accounts), sem consultar as APIs deles.
        members = MemberProjection()
        member_consumers = [
            StateConsumer(
                runtime.stream,
                members,
                durable=f"ipm-user-api-{name}-{instance}",
                stream="DESIRED",
                filter_subject=subject,
                inactive_threshold_seconds=300,
                traced=False,
                on_cycle=runtime.health.beat,
            )
            for name, subject in (
                ("users", USER_SUBJECT),
                ("serviceaccounts", SERVICEACCOUNT_SUBJECT),
            )
        ]
        for index, consumer in enumerate(member_consumers):
            runtime.start(f"member-projection-{index}", consumer.run(runtime.stop))

        def is_catalog_synced() -> bool:
            return (
                bool(catalog_consumers)
                and all(c.is_synced for c in catalog_consumers.values())
                and organization_consumer.is_synced
                and all(consumer.is_synced for consumer in member_consumers)
            )

        app = create_app(
            Dependencies(
                settings=api,
                authenticator=TokenVerifier(settings.auth, http),
                repository=SsotRepository(pool),
                organizations=organizations,
                members=members,
                admissions=SsotAdmissionStore(pool),
                catalog=catalog,
                is_catalog_synced=is_catalog_synced,
                is_ready=lambda: runtime.client.is_connected and is_catalog_synced(),
            )
        )
        runtime.start("http", serve_http(app, host=api.host, port=api.port, stop=runtime.stop))
        logger.info("user api started")
        # As probes são rotas da própria aplicação HTTP (`http/health_routes.py`).
        return await runtime.serve(health_port=None)


def main() -> None:
    start_role("api", UserApiSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
