"""Entrypoint do Receiver de Account (`core-account-receiver`, decisão 0015).

Só inicializa e encerra: valida a configuração, abre as conexões e serve a aplicação HTTP. A
lógica fica nos módulos de cada responsabilidade.
"""

import logging

import httpx

from core_account.common.database import open_pool
from core_account.common.http.server import serve_http
from core_account.common.lifecycle import start_role
from core_account.common.messaging import StreamPublisher
from core_account.common.runtime import role_runtime
from core_account.receiver.auth.tokens import TokenVerifier
from core_account.receiver.domain.ratelimit import SlidingWindowLimiter
from core_account.receiver.http.app import Dependencies, create_app
from core_account.receiver.settings import AccountReceiverSettings, missing_required
from core_account.receiver.store.repository import SsotRepository
from core_account.receiver.transport.peers import PeerResources

logger = logging.getLogger(__name__)


async def run(settings: AccountReceiverSettings) -> int:
    async with role_runtime(settings.messaging, name="core-account-receiver") as runtime:
        http = httpx.AsyncClient(timeout=5.0)
        runtime.close_after(http.aclose)
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)
        api = settings.api
        app = create_app(
            Dependencies(
                settings=api,
                authenticator=TokenVerifier(settings.auth, http),
                repository=SsotRepository(pool),
                publisher=StreamPublisher(runtime.stream),
                resources=PeerResources(settings.peers, http),
                is_ready=lambda: runtime.client.is_connected,
                limiter=SlidingWindowLimiter(
                    api.anonymous_rate_limit, api.anonymous_rate_window_seconds
                ),
            )
        )
        runtime.start("http", serve_http(app, host=api.host, port=api.port, stop=runtime.stop))
        logger.info("account api started")
        # As probes são rotas da própria aplicação HTTP (`http/health_routes.py`).
        return await runtime.serve(health_port=None)


def main() -> None:
    start_role("receiver", AccountReceiverSettings, missing_required, run)


if __name__ == "__main__":
    main()
