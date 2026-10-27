"""Entrypoint do Receiver de User (`ipm-user-receiver`, decisão 0015).

Só inicializa e encerra: valida a configuração, abre as conexões e serve a aplicação HTTP. A
lógica fica nos módulos de cada responsabilidade.
"""

import logging
import sys

import httpx

from ipm_user.common.catalog import AccessCatalog
from ipm_user.common.database import open_pool
from ipm_user.common.http.server import serve_http
from ipm_user.common.lifecycle import start_role
from ipm_user.common.messaging import StateConsumer, StreamPublisher, new_instance_name
from ipm_user.common.runtime import role_runtime
from ipm_user.receiver.auth.tokens import TokenVerifier
from ipm_user.receiver.http.app import Dependencies, create_app
from ipm_user.receiver.settings import UserReceiverSettings, missing_required
from ipm_user.receiver.store.repository import SsotRepository
from ipm_user.receiver.transport.catalog_consumer import CatalogWatcher
from ipm_user.receiver.transport.organizations import OrganizationPeer
from ipm_user.receiver.transport.serviceaccounts import ServiceAccountPeer

logger = logging.getLogger(__name__)


async def run(settings: UserReceiverSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-user-receiver") as runtime:
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
            ("permissions", "manager.desired.ipm.permission.>"),
            ("roles", "manager.desired.ipm.role.>"),
            ("groups", "manager.desired.ipm.group.>"),
        ):
            consumer = StateConsumer(
                runtime.stream,
                watcher,
                durable=f"ipm-user-receiver-{suffix}-{instance}",
                stream="DESIRED",
                filter_subject=subject,
                inactive_threshold_seconds=300,
                traced=False,
                on_cycle=runtime.health.beat,
            )
            catalog_consumers[suffix] = consumer
            runtime.start(suffix, consumer.run(runtime.stop))

        def is_catalog_synced() -> bool:
            return bool(catalog_consumers) and all(c.is_synced for c in catalog_consumers.values())

        app = create_app(
            Dependencies(
                settings=api,
                authenticator=TokenVerifier(settings.auth, http),
                repository=SsotRepository(pool),
                organizations=OrganizationPeer(settings.peers, http),
                serviceaccounts=ServiceAccountPeer(settings.peers, http),
                publisher=StreamPublisher(runtime.stream),
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
    start_role("receiver", UserReceiverSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
