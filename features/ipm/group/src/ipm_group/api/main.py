"""Entrypoint da API de Grupo (`ipm-group-api`, decisões 0015, 0085, 0088 e 0098).

Só inicializa e encerra: valida a configuração, abre as conexões e serve a aplicação HTTP.
"""

import logging
import sys

import httpx

from ipm_group.api.auth.tokens import TokenVerifier
from ipm_group.api.http.app import Dependencies, create_app
from ipm_group.api.settings import GroupApiSettings, missing_required
from ipm_group.api.store.admission import SsotAdmissionStore
from ipm_group.api.store.repository import SsotRepository
from ipm_group.api.transport.peers import OrganizationPeer, ServiceAccountPeer, UserPeer
from ipm_group.common.catalog import RolesCatalog
from ipm_group.common.catalog_watcher import RoleCatalogWatcher
from ipm_group.common.database import open_pool
from ipm_group.common.http.server import serve_http
from ipm_group.common.lifecycle import start_role
from ipm_group.common.messaging import StateConsumer, new_instance_name
from ipm_group.common.runtime import role_runtime

logger = logging.getLogger(__name__)


async def run(settings: GroupApiSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-group-api") as runtime:
        http = httpx.AsyncClient(timeout=settings.peers.timeout_seconds)
        runtime.close_after(http.aclose)
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)
        catalog = RolesCatalog()
        runtime.start(
            "role-catalog",
            StateConsumer(
                runtime.stream,
                RoleCatalogWatcher(catalog),
                durable=f"ipm-group-api-roles-{new_instance_name()}",
                stream="DESIRED",
                filter_subject="manager.desired.ipm.role.>",
                inactive_threshold_seconds=300,
                traced=False,
                on_cycle=runtime.health.beat,
            ).run(runtime.stop),
        )
        app = create_app(
            Dependencies(
                settings=settings.api,
                authenticator=TokenVerifier(settings.auth, http),
                repository=SsotRepository(pool),
                organizations=OrganizationPeer(settings.peers, http),
                users=UserPeer(settings.peers, http),
                serviceaccounts=ServiceAccountPeer(settings.peers, http),
                admissions=SsotAdmissionStore(pool),
                catalog=catalog,
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
        logger.info("group api started")
        return await runtime.serve(health_port=None)


def main() -> None:
    start_role("api", GroupApiSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
