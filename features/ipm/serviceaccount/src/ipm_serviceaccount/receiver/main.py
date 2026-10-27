"""Entrypoint do Receiver de Service Account (`ipm-serviceaccount-receiver`, decisão 0015).

Só inicializa e encerra: valida a configuração, abre as conexões e serve a aplicação HTTP. A
lógica fica nos módulos de cada responsabilidade.
"""

import logging
import sys

import httpx

from ipm_serviceaccount.common.catalog import AccessCatalog
from ipm_serviceaccount.common.database import open_pool
from ipm_serviceaccount.common.http.server import serve_http
from ipm_serviceaccount.common.lifecycle import start_role
from ipm_serviceaccount.common.messaging import StateConsumer, StreamPublisher, new_instance_name
from ipm_serviceaccount.common.runtime import role_runtime
from ipm_serviceaccount.receiver.auth.tokens import TokenVerifier
from ipm_serviceaccount.receiver.http.app import Dependencies, create_app
from ipm_serviceaccount.receiver.settings import ServiceaccountReceiverSettings, missing_required
from ipm_serviceaccount.receiver.store.repository import SsotRepository
from ipm_serviceaccount.receiver.transport.catalog_consumer import CatalogWatcher
from ipm_serviceaccount.receiver.transport.organizations import OrganizationPeer
from ipm_serviceaccount.receiver.transport.users import UserPeer

logger = logging.getLogger(__name__)


async def run(settings: ServiceaccountReceiverSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-serviceaccount-receiver") as runtime:
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
        ):
            consumer = StateConsumer(
                runtime.stream,
                watcher,
                durable=f"ipm-serviceaccount-receiver-{suffix}-{instance}",
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
                users=UserPeer(settings.peers, http),
                publisher=StreamPublisher(runtime.stream),
                catalog=catalog,
                is_catalog_synced=is_catalog_synced,
                is_ready=lambda: runtime.client.is_connected and is_catalog_synced(),
            )
        )
        runtime.start("http", serve_http(app, host=api.host, port=api.port, stop=runtime.stop))
        logger.info("serviceaccount api started")
        # As probes são rotas da própria aplicação HTTP (`http/health_routes.py`).
        return await runtime.serve(health_port=None)


def main() -> None:
    start_role(
        "receiver", ServiceaccountReceiverSettings, missing_required, run, cli_args=sys.argv[1:]
    )


if __name__ == "__main__":
    main()
