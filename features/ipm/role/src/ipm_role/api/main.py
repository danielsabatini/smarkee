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
from ipm_role.api.transport.peers import OrganizationPeer, RoleUsagePeer, UserPeer
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
        runtime.start(
            "permission-catalog",
            StateConsumer(
                runtime.stream,
                PermissionCatalogWatcher(grantable),
                durable=f"ipm-role-api-permissions-{new_instance_name()}",
                stream="DESIRED",
                filter_subject="manager.desired.ipm.permission.>",
                inactive_threshold_seconds=300,
                traced=False,
                on_cycle=runtime.health.beat,
            ).run(runtime.stop),
        )
        app = create_app(
            Dependencies(
                settings=settings.api,
                repository=SsotRepository(pool),
                organizations=OrganizationPeer(settings.peers, http),
                users=UserPeer(settings.peers, http),
                role_usage=RoleUsagePeer(settings.peers, http),
                grantable=grantable,
                admissions=SsotAdmissionStore(pool),
                authenticator=TokenVerifier(settings.auth, http),
                is_ready=lambda: runtime.client.is_connected,
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
