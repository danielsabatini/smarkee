"""Entrypoint do Publisher de `ipm.organization` (decisões 0015 e 0033).

Contêiner `ipm-organization-publisher`.
Lê o outbox do tipo e publica no transporte, em ordem; uma instância ativa por trava consultiva.
Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o Publisher. Uma recusa
permanente não derruba o processo: o Publisher sai de `ready` e quem opera é avisado (decisão 0018).
"""

import logging
import sys

from ipm_organization.common.lifecycle import start_role
from ipm_organization.common.messaging import StreamPublisher
from ipm_organization.common.runtime import role_runtime
from ipm_organization.publisher.outbox.publication import OutboxPublisher
from ipm_organization.publisher.settings import IpmOrganizationPublisherSettings, missing_required

logger = logging.getLogger(__name__)


async def run(settings: IpmOrganizationPublisherSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-organization-publisher") as runtime:
        publisher = OutboxPublisher(
            settings.database, StreamPublisher(runtime.stream), on_cycle=runtime.health.beat
        )
        runtime.health.add_check("publication", lambda: not publisher.blocked_by_permanent_failure)
        runtime.start("publisher", publisher.run(runtime.stop))
        logger.info("ipm organization publisher started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role(
        "publisher",
        IpmOrganizationPublisherSettings,
        missing_required,
        run,
        cli_args=sys.argv[1:],
    )


if __name__ == "__main__":
    main()
