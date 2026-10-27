"""Entrypoint da API de Organization (`ipm-organization-api`, decisões 0015, 0098 e 0100).

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
from ipm_organization.api.transport.billing_accounts import BillingAccountPeer
from ipm_organization.api.transport.member_projection import (
    SERVICEACCOUNT_SUBJECT,
    USER_SUBJECT,
    MemberProjection,
)
from ipm_organization.common.database import open_pool
from ipm_organization.common.dependents import (
    GROUP_SUBJECT,
    ROLE_SUBJECT,
    DependentsProjection,
)
from ipm_organization.common.http.server import serve_http
from ipm_organization.common.lifecycle import start_role
from ipm_organization.common.messaging import StateConsumer, new_instance_name
from ipm_organization.common.runtime import role_runtime
from ipm_organization.common.user_access import desired_user_access

logger = logging.getLogger(__name__)


async def run(settings: OrganizationApiSettings) -> int:
    instance = new_instance_name()

    async with role_runtime(settings.messaging, name="ipm-organization-api") as runtime:
        http = httpx.AsyncClient(timeout=5.0)
        runtime.close_after(http.aclose)
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)

        # Pertencimento do solicitante (Organization de cada usuário e service account)
        members = MemberProjection()
        member_consumers = [
            StateConsumer(
                runtime.stream,
                members,
                durable=f"ipm-organization-api-{name}-{instance}",
                stream="DESIRED",
                filter_subject=subject,
                inactive_threshold_seconds=300,
                traced=False,
                on_cycle=runtime.health.beat,
            )
            for name, subject in (
                ("users", USER_SUBJECT),
                ("serviceaccounts", SERVICEACCOUNT_SUBJECT),
            )
        ]
        for index, consumer in enumerate(member_consumers):
            runtime.start(f"member-projection-{index}", consumer.run(runtime.stop))

        # Recursos dependentes de cada Organization (user, serviceaccount, group, role)
        dependents = DependentsProjection()
        dependent_consumers = [
            StateConsumer(
                runtime.stream,
                dependents,
                durable=f"ipm-organization-api-dependents-{name}-{instance}",
                stream="DESIRED",
                filter_subject=subject,
                inactive_threshold_seconds=300,
                traced=False,
                on_cycle=runtime.health.beat,
            )
            for name, subject in (
                ("users", USER_SUBJECT),
                ("serviceaccounts", SERVICEACCOUNT_SUBJECT),
                ("groups", GROUP_SUBJECT),
                ("roles", ROLE_SUBJECT),
            )
        ]
        for index, consumer in enumerate(dependent_consumers):
            runtime.start(f"dependents-projection-{index}", consumer.run(runtime.stop))

        def is_synced() -> bool:
            return all(c.is_synced for c in member_consumers) and all(
                c.is_synced for c in dependent_consumers
            )

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
                members=members,
                dependents=dependents,
                billing_accounts=BillingAccountPeer(settings.peers, http),
                user_access_data=user_access_data,
                is_ready=lambda: runtime.client.is_connected and is_synced(),
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
