"""Entrypoint do Receiver de Organization (`ipm-organization-receiver`, decisão 0015).

Só inicializa e encerra: valida a configuração, abre as conexões e serve a aplicação HTTP. A
lógica fica nos módulos de cada responsabilidade.
"""

import logging
import sys

import httpx

from ipm_organization.common.database import open_pool
from ipm_organization.common.http.server import serve_http
from ipm_organization.common.lifecycle import start_role
from ipm_organization.common.messaging import StreamPublisher
from ipm_organization.common.runtime import role_runtime
from ipm_organization.receiver.auth.tokens import EmailVerification, TokenVerifier
from ipm_organization.receiver.http.app import Dependencies, create_app
from ipm_organization.receiver.settings import OrganizationReceiverSettings, missing_required
from ipm_organization.receiver.store.repository import SsotRepository

logger = logging.getLogger(__name__)


async def run(settings: OrganizationReceiverSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-organization-receiver") as runtime:
        http = httpx.AsyncClient(timeout=5.0)
        runtime.close_after(http.aclose)
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)
        api = settings.api
        app = create_app(
            Dependencies(
                settings=api,
                authenticator=TokenVerifier(settings.auth, http),
                email_verifier=EmailVerification(settings.auth, http),
                repository=SsotRepository(pool),
                publisher=StreamPublisher(runtime.stream),
                is_ready=lambda: runtime.client.is_connected,
            )
        )
        runtime.start("http", serve_http(app, host=api.host, port=api.port, stop=runtime.stop))
        logger.info("organization api started")
        # As probes são rotas da própria aplicação HTTP (`http/health_routes.py`).
        return await runtime.serve(health_port=None)


def main() -> None:
    start_role(
        "receiver", OrganizationReceiverSettings, missing_required, run, cli_args=sys.argv[1:]
    )


if __name__ == "__main__":
    main()
