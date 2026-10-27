"""Entrypoint da API de Role (`ipm-role-api`, decisões 0015, 0083, 0092 e 0098).

Só inicializa e encerra: valida a configuração, abre as conexões e serve a aplicação HTTP. A
lógica fica nos módulos de cada responsabilidade.
"""

import logging
import sys

import httpx

from ipm_role.api.auth.tokens import TokenVerifier
from ipm_role.api.http.app import Dependencies, create_app
from ipm_role.api.settings import RoleApiSettings, missing_required
from ipm_role.api.store.admission import SsotAdmissionStore
from ipm_role.api.store.repository import SsotRepository
from ipm_role.api.transport.catalog_consumer import PermissionCatalogWatcher
from ipm_role.api.transport.member_projection import (
    SERVICEACCOUNT_SUBJECT,
    USER_SUBJECT,
    MemberProjection,
)
from ipm_role.api.transport.organization_projection import (
    ORGANIZATION_SUBJECT,
    OrganizationProjection,
)
from ipm_role.api.transport.peers import RoleUsagePeer
from ipm_role.common.catalog import GrantableCatalog
from ipm_role.common.database import open_pool
from ipm_role.common.http.server import serve_http
from ipm_role.common.lifecycle import start_role
from ipm_role.common.messaging import StateConsumer, new_instance_name
from ipm_role.common.runtime import role_runtime

logger = logging.getLogger(__name__)


async def run(settings: RoleApiSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-role-api") as runtime:
        http = httpx.AsyncClient(timeout=settings.peers.timeout_seconds)
        runtime.close_after(http.aclose)
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)
        # Teto de permissões de uma Role `custom`: as delegáveis à Organization, em tempo real.
        grantable = GrantableCatalog()
        permissions = StateConsumer(
            runtime.stream,
            PermissionCatalogWatcher(grantable),
            durable=f"ipm-role-api-permissions-{new_instance_name()}",
            stream="DESIRED",
            filter_subject="manager.desired.ipm.permission.>",
            inactive_threshold_seconds=300,
            traced=False,
            on_cycle=runtime.health.beat,
        )
        runtime.start("permission-catalog", permissions.run(runtime.stop))
        # Dono e ciclo de vida das Organizations, sem consulta à API da Organization (0100).
        organizations = OrganizationProjection()
        organization_consumer = StateConsumer(
            runtime.stream,
            organizations,
            durable=f"ipm-role-api-organizations-{new_instance_name()}",
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
                durable=f"ipm-role-api-{name}-{new_instance_name()}",
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

        def is_synced() -> bool:
            return (
                permissions.is_synced
                and organization_consumer.is_synced
                and all(consumer.is_synced for consumer in member_consumers)
            )

        app = create_app(
            Dependencies(
                settings=settings.api,
                repository=SsotRepository(pool),
                organizations=organizations,
                members=members,
                role_usage=RoleUsagePeer(settings.peers, http),
                grantable=grantable,
                admissions=SsotAdmissionStore(pool),
                authenticator=TokenVerifier(settings.auth, http),
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
        logger.info("role api started")
        # As probes são rotas da própria aplicação HTTP (`http/health_routes.py`).
        return await runtime.serve(health_port=None)


def main() -> None:
    start_role("api", RoleApiSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
