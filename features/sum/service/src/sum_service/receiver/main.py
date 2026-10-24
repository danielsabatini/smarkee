"""Entrypoint do Receiver de `sum.service` (`sum-service-receiver`, decisões 0015 e 0033).

Autentica o solicitante, confere a permissão da ação, publica o `requested` e responde. Só inicializa e
encerra:
valida a configuração, abre as conexões e serve a API.
"""

import logging
import sys

import httpx
from psycopg.rows import dict_row

from sum_service.common.database import open_pool
from sum_service.common.http.server import serve_http
from sum_service.common.lifecycle import start_role
from sum_service.common.runtime import role_runtime
from sum_service.receiver.auth.tokens import TokenVerifier
from sum_service.receiver.http.app import Dependencies, create_app
from sum_service.receiver.settings import SumServiceReceiverSettings, missing_required
from sum_service.receiver.store.repository import Repository
from sum_service.receiver.transport.dependents import PeerDependents
from sum_service.receiver.transport.messaging import RequestedPublisher

logger = logging.getLogger(__name__)


async def run(settings: SumServiceReceiverSettings) -> int:
    async with role_runtime(settings.messaging, name="sum-service-receiver") as runtime:
        http = httpx.AsyncClient(timeout=5.0)
        runtime.close_after(http.aclose)
        pool = await open_pool(settings.database, row_factory=dict_row)
        runtime.close_after(pool.close)
        app = create_app(
            Dependencies(
                verifier=TokenVerifier(settings.auth, http),
                repository=Repository(pool),
                publisher=RequestedPublisher(runtime.stream),
                health=runtime.health,
                dependents=PeerDependents(settings.peers, http),
            )
        )
        runtime.start(
            "http",
            serve_http(app, host=settings.api.host, port=settings.api.port, stop=runtime.stop),
        )
        logger.info("sum service receiver started")
        # As probes são rotas da própria aplicação HTTP (`http/app.py`).
        return await runtime.serve(health_port=None)


def main() -> None:
    start_role("receiver", SumServiceReceiverSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
