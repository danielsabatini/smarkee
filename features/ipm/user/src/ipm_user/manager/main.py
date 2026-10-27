"""Entrypoint do Manager de User (`ipm-user-manager`, decisões 0015, 0019 e 0063).

Consome `requested` e escreve no SSOT; só insere no outbox. A
publicação do outbox é do Publisher (`../publisher`). Só inicializa e encerra: valida a
configuração, abre as conexões e roda os consumers.
"""

import logging
import sys

from ipm_user.common.database import open_pool
from ipm_user.common.lifecycle import start_role
from ipm_user.common.runtime import role_runtime
from ipm_user.manager.domain.kind import user_kind
from ipm_user.manager.handlers.requested import RequestedHandler
from ipm_user.manager.settings import UserManagerSettings, missing_required
from ipm_user.manager.transport.consumers import RequestedConsumer

logger = logging.getLogger(__name__)


async def run(settings: UserManagerSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-user-manager") as runtime:
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)
        kind = user_kind()
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
        logger.info("user manager started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role("manager", UserManagerSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
