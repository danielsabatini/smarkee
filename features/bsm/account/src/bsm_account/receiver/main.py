"""Entrypoint do Receiver de Billing Account (`bsm-account-receiver`, decisão 0015).

Só inicializa e encerra: valida a configuração, abre as conexões e serve a aplicação HTTP. A
lógica fica nos módulos de cada responsabilidade.
"""

import logging
import sys

import httpx

from bsm_account.common.database import open_pool
from bsm_account.common.http.server import serve_http
from bsm_account.common.lifecycle import start_role
from bsm_account.common.messaging import StreamPublisher
from bsm_account.common.runtime import role_runtime
from bsm_account.receiver.auth.tokens import EmailVerification, TokenVerifier
from bsm_account.receiver.http.app import Dependencies, create_app
from bsm_account.receiver.settings import AccountReceiverSettings, missing_required
from bsm_account.receiver.store.repository import SsotRepository
from bsm_account.receiver.transport.organizations import OrganizationPeer

logger = logging.getLogger(__name__)


async def run(settings: AccountReceiverSettings) -> int:
    async with role_runtime(settings.messaging, name="bsm-account-receiver") as runtime:
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
                organizations=OrganizationPeer(settings.peers, http),
                publisher=StreamPublisher(runtime.stream),
                is_ready=lambda: runtime.client.is_connected,
            )
        )
        runtime.start("http", serve_http(app, host=api.host, port=api.port, stop=runtime.stop))
        logger.info("account api started")
        # As probes são rotas da própria aplicação HTTP (`http/health_routes.py`).
        return await runtime.serve(health_port=None)


def main() -> None:
    start_role("receiver", AccountReceiverSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
