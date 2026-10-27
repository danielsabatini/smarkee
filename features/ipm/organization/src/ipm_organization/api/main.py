"""Entrypoint da API de Organization (`ipm-organization-api`, decisões 0015 e 0098).

Só inicializa e encerra: valida a configuração, abre as conexões e serve a aplicação HTTP. A
lógica fica nos módulos de cada responsabilidade.
"""

import logging
import sys

import httpx

from ipm_organization.api.auth.tokens import EmailVerification, TokenVerifier
from ipm_organization.api.http.app import Dependencies, create_app
from ipm_organization.api.settings import OrganizationApiSettings, missing_required
from ipm_organization.api.store.admission import SsotAdmissionStore
from ipm_organization.api.store.repository import SsotRepository
from ipm_organization.api.transport.users import UserPeer
from ipm_organization.common.database import open_pool
from ipm_organization.common.http.server import serve_http
from ipm_organization.common.lifecycle import start_role
from ipm_organization.common.runtime import role_runtime
from ipm_organization.common.user_access import desired_user_access

logger = logging.getLogger(__name__)


async def run(settings: OrganizationApiSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-organization-api") as runtime:
        http = httpx.AsyncClient(timeout=5.0)
        runtime.close_after(http.aclose)
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)
        user_access_data = desired_user_access(
            user_executor_account_id=settings.user_access.user_executor_account_id,
            user_observer_account_id=settings.user_access.user_observer_account_id,
            serviceaccount_executor_account_id=settings.user_access.serviceaccount_executor_account_id,
            serviceaccount_observer_account_id=settings.user_access.serviceaccount_observer_account_id,
            serviceaccount_controller_account_id=settings.user_access.serviceaccount_controller_account_id,
            user_controller_account_id=settings.user_access.user_controller_account_id,
        )
        app = create_app(
            Dependencies(
                settings=settings,
                authenticator=TokenVerifier(settings.auth, http),
                email_verifier=EmailVerification(settings.auth, http),
                repository=SsotRepository(pool),
                admissions=SsotAdmissionStore(pool),
                users=UserPeer(settings.peers, http),
                user_access_data=user_access_data,
                is_ready=lambda: runtime.client.is_connected,
            )
        )
        runtime.start(
            "http",
            serve_http(app, host=settings.api.host, port=settings.api.port, stop=runtime.stop),
        )
        logger.info("organization api started")
        # As probes são rotas da própria aplicação HTTP (`http/health_routes.py`).
        return await runtime.serve(health_port=None)


def main() -> None:
    start_role("api", OrganizationApiSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
