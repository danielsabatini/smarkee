"""Entrypoint do Publisher de `sum.service` (decisões 0015 e 0033).

Contêiner `sum-service-publisher`.
Lê o outbox do tipo e publica no transporte, em ordem; uma instância ativa por trava consultiva.
Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o Publisher. Uma recusa
permanente não derruba o processo: o Publisher sai de `ready` e quem opera é avisado (decisão 0018).
"""

import logging
import sys

from sum_service.common.lifecycle import start_role
from sum_service.common.messaging import StreamPublisher
from sum_service.common.runtime import role_runtime
from sum_service.publisher.outbox.publication import OutboxPublisher
from sum_service.publisher.settings import SumServicePublisherSettings, missing_required

logger = logging.getLogger(__name__)


async def run(settings: SumServicePublisherSettings) -> int:
    async with role_runtime(settings.messaging, name="sum-service-publisher") as runtime:
        publisher = OutboxPublisher(
            settings.database, StreamPublisher(runtime.stream), on_cycle=runtime.health.beat
        )
        runtime.health.add_check("publication", lambda: not publisher.blocked_by_permanent_failure)
        runtime.start("publisher", publisher.run(runtime.stop))
        logger.info("sum service publisher started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role(
        "publisher", SumServicePublisherSettings, missing_required, run, cli_args=sys.argv[1:]
    )


if __name__ == "__main__":
    main()
