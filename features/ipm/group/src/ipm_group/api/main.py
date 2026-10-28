"""Entrypoint do Receiver de Group (`ipm-group-api`, decisões 0088 e 0098).

Valida a configuração, conecta ao banco e ao NATS e serve a API HTTP. As regras de admissão e
consulta ficam em `http/`, `domain/` e `store/`.
"""

import logging
import sys

import httpx

from ipm_group.api.auth.tokens import TokenVerifier
from ipm_group.api.http.app import Dependencies, create_app
from ipm_group.api.settings import GroupApiSettings, missing_required
from ipm_group.api.store.admission import SsotAdmissionStore
from ipm_group.api.store.repository import SsotRepository
from ipm_group.api.transport.group_usage_projection import GroupUsageProjection
from ipm_group.api.transport.member_projection import (
    SERVICEACCOUNT_SUBJECT,
    USER_SUBJECT,
    MemberProjection,
)
from ipm_group.api.transport.organization_projection import (
    ORGANIZATION_SUBJECT,
    OrganizationProjection,
)
from ipm_group.common.catalog import RolesCatalog
from ipm_group.common.catalog_watcher import RoleCatalogWatcher
from ipm_group.common.database import open_pool
from ipm_group.common.http.server import serve_http
from ipm_group.common.lifecycle import start_role
from ipm_group.common.messaging import StateConsumer, new_instance_name
from ipm_group.common.runtime import role_runtime

logger = logging.getLogger(__name__)


async def run(settings: GroupApiSettings) -> int:
    instance = new_instance_name()

    async with role_runtime(settings.messaging, name="ipm-group-api") as runtime:
        http = httpx.AsyncClient(timeout=5.0)
        runtime.close_after(http.aclose)
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)
        catalog = RolesCatalog()
        roles = StateConsumer(
            runtime.stream,
            RoleCatalogWatcher(catalog),
            durable=f"ipm-group-api-roles-{instance}",
            stream="DESIRED",
            filter_subject="desired.ipm.role.>",
            inactive_threshold_seconds=300,
            traced=False,
            on_cycle=runtime.health.beat,
        )
        runtime.start("role-catalog", roles.run(runtime.stop))
        # Dono e ciclo de vida das Organizations, sem consulta à API da Organization (0100).
        organizations = OrganizationProjection()
        organization_consumer = StateConsumer(
            runtime.stream,
            organizations,
            durable=f"ipm-group-api-organizations-{instance}",
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
                durable=f"ipm-group-api-{name}-{instance}",
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

        # Uso de Grupos por usuários, sem consulta HTTP (0100).
        group_usage = GroupUsageProjection()
        group_usage_consumer = StateConsumer(
            runtime.stream,
            group_usage,
            durable=f"ipm-group-api-usage-{instance}",
            stream="DESIRED",
            filter_subject=USER_SUBJECT,
            inactive_threshold_seconds=300,
            traced=False,
            on_cycle=runtime.health.beat,
        )
        runtime.start("group-usage-projection", group_usage_consumer.run(runtime.stop))

        def is_synced() -> bool:
            return (
                roles.is_synced
                and organization_consumer.is_synced
                and all(consumer.is_synced for consumer in member_consumers)
                and group_usage_consumer.is_synced
            )

        app = create_app(
            Dependencies(
                settings=settings.api,
                authenticator=TokenVerifier(settings.auth, http),
                repository=SsotRepository(pool),
                organizations=organizations,
                users=group_usage,
                members=members,
                admissions=SsotAdmissionStore(pool),
                catalog=catalog,
                is_ready=lambda: runtime.client.is_connected and is_synced(),
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
            "group api started",
            extra={
                "smarkee.api.host": settings.api.host,
                "smarkee.api.port": settings.api.port,
            },
        )
        # As probes são rotas da própria aplicação HTTP (`http/health_routes.py`).
        return await runtime.serve(health_port=None)


def main(argv: list[str] | None = None) -> None:
    start_role("api", GroupApiSettings, missing_required, run, cli_args=argv or sys.argv[1:])


if __name__ == "__main__":
    main()
