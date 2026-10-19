"""Entrypoint do Publisher de `@@DOTTED@@` (decisões 0015 e 0033).

Contêiner `@@KEBAB@@-publisher`.
Lê o outbox do tipo e publica no transporte, em ordem; uma instância ativa por trava consultiva.
Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o Publisher. Uma recusa
permanente não derruba o processo: o Publisher sai de `ready` e quem opera é avisado (decisão 0018).
"""

import logging

from @@PACKAGE@@.common.lifecycle import start_role
from @@PACKAGE@@.common.messaging import StreamPublisher
from @@PACKAGE@@.common.runtime import role_runtime
from @@PACKAGE@@.publisher.outbox.publication import OutboxPublisher
from @@PACKAGE@@.publisher.settings import @@CLASS@@PublisherSettings, missing_required

logger = logging.getLogger(__name__)


async def run(settings: @@CLASS@@PublisherSettings) -> int:
    async with role_runtime(settings.messaging, name="@@KEBAB@@-publisher") as runtime:
        publisher = OutboxPublisher(
            settings.database, StreamPublisher(runtime.stream), on_cycle=runtime.health.beat
        )
        runtime.health.add_check("publication", lambda: not publisher.blocked_by_permanent_failure)
        runtime.start("publisher", publisher.run(runtime.stop))
        logger.info("@@SPACED@@ publisher started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role("publisher", @@CLASS@@PublisherSettings, missing_required, run)


if __name__ == "__main__":
    main()
