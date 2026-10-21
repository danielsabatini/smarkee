"""Entrypoint do Publisher de `core.account` (decisões 0015 e 0033).

Contêiner `core-account-publisher`.
Lê o outbox do tipo e publica no transporte, em ordem; uma instância ativa por trava consultiva.
Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o Publisher. Uma recusa
permanente não derruba o processo: o Publisher sai de `ready` e quem opera é avisado (decisão 0018).
"""

import logging
import sys

from core_account.common.lifecycle import start_role
from core_account.common.messaging import StreamPublisher
from core_account.common.runtime import role_runtime
from core_account.publisher.outbox.publication import OutboxPublisher
from core_account.publisher.settings import CoreAccountPublisherSettings, missing_required

logger = logging.getLogger(__name__)


async def run(settings: CoreAccountPublisherSettings) -> int:
    async with role_runtime(settings.messaging, name="core-account-publisher") as runtime:
        publisher = OutboxPublisher(
            settings.database, StreamPublisher(runtime.stream), on_cycle=runtime.health.beat
        )
        runtime.health.add_check("publication", lambda: not publisher.blocked_by_permanent_failure)
        runtime.start("publisher", publisher.run(runtime.stop))
        logger.info("core account publisher started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role(
        "publisher",
        CoreAccountPublisherSettings,
        missing_required,
        run,
        cli_args=sys.argv[1:],
    )


if __name__ == "__main__":
    main()
