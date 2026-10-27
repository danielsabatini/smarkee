"""Entrypoint do Manager de Service Account (`ipm-serviceaccount-manager`, decisões 0015, 0019 e 0063).

Consome `requested` e escreve no SSOT; só insere no outbox. A
publicação do outbox é do Publisher (`../publisher`). Só inicializa e encerra: valida a
configuração, abre as conexões e roda os consumers.
"""

import logging
import sys

from ipm_serviceaccount.common.database import open_pool
from ipm_serviceaccount.common.lifecycle import start_role
from ipm_serviceaccount.common.runtime import role_runtime
from ipm_serviceaccount.manager.domain.kind import serviceaccount_kind
from ipm_serviceaccount.manager.handlers.requested import RequestedHandler
from ipm_serviceaccount.manager.settings import ServiceaccountManagerSettings, missing_required
from ipm_serviceaccount.manager.transport.consumers import RequestedConsumer

logger = logging.getLogger(__name__)


async def run(settings: ServiceaccountManagerSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-serviceaccount-manager") as runtime:
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)
        kind = serviceaccount_kind()
        consumers = {
            "requested": RequestedConsumer(
                runtime.stream,
                pool,
                kind,
                handler=RequestedHandler(),
                on_cycle=runtime.health.beat,
            ),
        }
        for name, consumer in consumers.items():
            runtime.start(name, consumer.run(runtime.stop))
        logger.info("serviceaccount manager started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role(
        "manager", ServiceaccountManagerSettings, missing_required, run, cli_args=sys.argv[1:]
    )


if __name__ == "__main__":
    main()
