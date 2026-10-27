"""Entrypoint da API de Permission (`ipm-permission-api`, decisões 0015 e 0098).

Só inicializa e encerra: valida a configuração, abre as conexões e serve a aplicação HTTP. A
lógica fica nos módulos de cada responsabilidade.
"""

import logging
import sys

import httpx

from ipm_permission.api.auth.tokens import TokenVerifier
from ipm_permission.api.http.app import Dependencies, create_app
from ipm_permission.api.settings import PermissionApiSettings, missing_required
from ipm_permission.api.store.admission import SsotAdmissionStore
from ipm_permission.api.store.repository import SsotRepository
from ipm_permission.common.database import open_pool
from ipm_permission.common.http.server import serve_http
from ipm_permission.common.lifecycle import start_role
from ipm_permission.common.runtime import role_runtime

logger = logging.getLogger(__name__)


async def run(settings: PermissionApiSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-permission-api") as runtime:
        http = httpx.AsyncClient(timeout=5.0)
        runtime.close_after(http.aclose)
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)
        app = create_app(
            Dependencies(
                authenticator=TokenVerifier(settings.auth, http),
                repository=SsotRepository(pool),
                admissions=SsotAdmissionStore(pool),
                is_ready=lambda: runtime.client.is_connected,
            )
        )
        runtime.start(
            "http",
            serve_http(app, host=settings.api.host, port=settings.api.port, stop=runtime.stop),
        )
        logger.info("permission api started")
        # As probes são rotas da própria aplicação HTTP (`http/health_routes.py`).
        return await runtime.serve(health_port=None)


def main() -> None:
    start_role("api", PermissionApiSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
