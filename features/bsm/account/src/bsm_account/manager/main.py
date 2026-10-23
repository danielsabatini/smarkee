"""Entrypoint do Manager de Billing Account (`bsm-account-manager`, decisões 0015, 0019 e 0063).

Consome `requested`, `observed` e `completed`/`failed` e escreve no SSOT; só insere no outbox. A
publicação do outbox é do Publisher (`../publisher`). Só inicializa e encerra: valida a
configuração, abre as conexões e roda os consumers.
"""

import logging
import sys

from bsm_account.common.database import open_pool
from bsm_account.common.lifecycle import start_role
from bsm_account.common.runtime import role_runtime
from bsm_account.manager.domain.kind import ACCOUNT
from bsm_account.manager.handlers.observed import ObservedHandler
from bsm_account.manager.handlers.requested import RequestedHandler
from bsm_account.manager.handlers.result import ResultHandler
from bsm_account.manager.settings import AccountManagerSettings, missing_required
from bsm_account.manager.transport.account_updated import AccountUpdatedConsumer
from bsm_account.manager.transport.consumers import (
    ObservedConsumer,
    RequestedConsumer,
    ResultConsumer,
)

logger = logging.getLogger(__name__)


async def run(settings: AccountManagerSettings) -> int:
    async with role_runtime(settings.messaging, name="bsm-account-manager") as runtime:
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)
        consumers = {
            "requested": RequestedConsumer(
                runtime.stream,
                pool,
                ACCOUNT,
                handler=RequestedHandler(),
                on_cycle=runtime.health.beat,
            ),
            "observed": ObservedConsumer(
                runtime.stream,
                pool,
                ACCOUNT,
                handler=ObservedHandler(
                    progress_deadline_seconds=settings.loop.progress_deadline_seconds
                ),
                on_cycle=runtime.health.beat,
            ),
            "result": ResultConsumer(
                runtime.stream,
                pool,
                ACCOUNT,
                handler=ResultHandler(failure_limit=settings.loop.failure_limit),
                on_cycle=runtime.health.beat,
            ),
            "account_updated": AccountUpdatedConsumer(
                runtime.stream,
                pool,
                ACCOUNT,
                on_cycle=runtime.health.beat,
            ),
        }
        for name, consumer in consumers.items():
            runtime.start(name, consumer.run(runtime.stop))
        logger.info("account manager started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role("manager", AccountManagerSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
