"""Entrypoint do Publisher de `ipm.user` (decisões 0015 e 0033).

Contêiner `ipm-user-publisher`.
Lê o outbox do tipo e publica no transporte, em ordem; uma instância ativa por trava consultiva.
Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o Publisher. Uma recusa
permanente não derruba o processo: o Publisher sai de `ready` e quem opera é avisado (decisão 0018).
"""

import logging
import sys

from ipm_user.common.lifecycle import start_role
from ipm_user.common.messaging import StreamPublisher
from ipm_user.common.runtime import role_runtime
from ipm_user.publisher.outbox.publication import OutboxPublisher
from ipm_user.publisher.settings import IpmUserPublisherSettings, missing_required

logger = logging.getLogger(__name__)


async def run(settings: IpmUserPublisherSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-user-publisher") as runtime:
        publisher = OutboxPublisher(
            settings.database, StreamPublisher(runtime.stream), on_cycle=runtime.health.beat
        )
        runtime.health.add_check("publication", lambda: not publisher.blocked_by_permanent_failure)
        runtime.start("publisher", publisher.run(runtime.stop))
        logger.info("ipm user publisher started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role(
        "publisher",
        IpmUserPublisherSettings,
        missing_required,
        run,
        cli_args=sys.argv[1:],
    )


if __name__ == "__main__":
    main()
