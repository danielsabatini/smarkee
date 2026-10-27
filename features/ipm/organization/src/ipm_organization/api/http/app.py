"""Aplicação HTTP da API (decisão 0098; `docs/loop/RESOURCE-CONTROL-LOOP.md` §6).

A API autentica, autoriza, valida e **admite a escrita de forma síncrona**: numa transação do SSOT
grava o recurso e o `desired` no outbox (o Publisher publica depois). Não há Operation: `POST`
responde `201`, `PATCH` responde `200` e `DELETE` responde `202`, todos com o `Resource`; a
convergência se acompanha lendo o recurso (`observedGeneration`, `phase` e `conditions`). Ela não
tem credencial no provedor de identidade. As leituras vêm das views do SSOT.

Quem age numa Organization (decisão 0077): o dono (root), o operador e os usuários dela, estes
reconhecidos pela API do User com o token de quem pede (decisão 0040). A Organization só é
removida vazia, sem usuários nem service accounts.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any, Literal, Protocol

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ipm_organization.api.domain import principal as permissions
from ipm_organization.api.domain.admission import Admission
from ipm_organization.api.domain.errors import (
    ApiError,
    bad_request,
    conflict,
    forbidden,
    not_found,
    unauthorized,
)
from ipm_organization.api.domain.principal import Principal
from ipm_organization.api.domain.records import ResourceRecord
from ipm_organization.api.domain.requests import checked_idempotency_key, request_digest
from ipm_organization.api.domain.views import organization_view
from ipm_organization.api.http.admission import admit
from ipm_organization.api.http.health_routes import register_health_routes
from ipm_organization.api.http.ports import (
    AdmissionStore,
    BillingAccounts,
    Dependents,
    EmailVerifier,
    Members,
    Repository,
)
from ipm_organization.api.http.trace_context import TraceContextMiddleware
from ipm_organization.api.settings import OrganizationApiSettings
from ipm_organization.common.contracts import generated
from ipm_organization.common.ids import new_identifier, utc_now
from ipm_organization.common.logging_config import bind_context

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 50
MAXIMUM_PAGE_SIZE = 200
RETRY_AFTER_SECONDS = "5"


class Authenticator(Protocol):
    async def verify(self, token: str) -> Principal: ...


@dataclass(frozen=True)
class Dependencies:
    settings: OrganizationApiSettings
    authenticator: Authenticator
    repository: Repository
    admissions: AdmissionStore
    members: Members
    dependents: Dependents
    billing_accounts: BillingAccounts
    email_verifier: EmailVerifier
    user_access_data: Mapping[str, Any] | None = None
    clock: Callable[[], datetime] = utc_now
    identifiers: Callable[[], str] = new_identifier
    is_ready: Callable[[], bool] = lambda: True
    """Prontidão das dependências críticas (NATS); usada por `/health/ready`."""


async def authenticate(request: Request) -> Principal:
    deps: Dependencies = request.app.state.dependencies
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthorized()
    principal = await deps.authenticator.verify(token.strip())
    bind_context(requested_by=principal.subject)
    return principal


Authenticated = Annotated[Principal, Depends(authenticate)]
IdempotencyKey = Annotated[str | None, Header()]
VersionQuery = Annotated[str, Query(alias="resourceVersion", pattern=r"^[0-9]{1,18}$")]


def create_app(deps: Dependencies) -> FastAPI:
    app = FastAPI(
        title="smarkee ipm organization api", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.dependencies = deps
    app.add_middleware(TraceContextMiddleware)
    _register_error_handlers(app)
    _register_routes(app, deps)
    register_health_routes(app, lambda: deps.is_ready())
    return app


# ---------------------------------------------------------------------- erros


def _error_response(error: ApiError) -> JSONResponse:
    body = generated.ApiError.model_validate(
        {
            "errorCode": error.error_code,
            "message": error.message,
            **({"field": error.field} if error.field else {}),
        }
    )
    return JSONResponse(
        status_code=error.status,
        content=body.model_dump(mode="json", exclude_none=True),
        headers=error.headers,
    )


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, error: ApiError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        logger.warning(
            "request rejected",
            extra={"smarkee.outcome": "rejected", "error.type": error.error_code},
        )
        return _error_response(error)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(  # pyright: ignore[reportUnusedFunction]
        _: Request, error: RequestValidationError
    ) -> JSONResponse:
        first = error.errors()[0]
        # Só o caminho do campo e a regra violada: nunca o valor enviado (`SCHEMA.md` §20.5).
        field = ".".join(str(part) for part in first["loc"][1:]) or None
        return _error_response(bad_request(f"Campo inválido: {first['msg']}", field=field))

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, error: Exception) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        logger.error("unexpected error", exc_info=error)
        return _error_response(
            ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "InternalError", "Erro interno.")
        )


# ---------------------------------------------------------------------- rotas


def _register_routes(app: FastAPI, deps: Dependencies) -> None:
    def require(principal: Principal, permission: str) -> None:
        if not principal.has_permission(permission):
            raise forbidden()

    def is_owner(principal: Principal, record: ResourceRecord) -> bool:
        return principal.is_operator or record.desired.get("ownerAccountId") == principal.subject

    async def member_organization(principal: Principal) -> str | None:
        """A Organization de que o solicitante é membro, pela projeção local (decisão 0100)."""
        return deps.members.organization_of(principal.subject)

    async def owned_organization(principal: Principal, organization_id: str) -> ResourceRecord:
        """A Organization, se o solicitante é o dono, o operador ou um usuário dela."""
        record = await deps.repository.get_organization(organization_id)
        if record is None:
            raise not_found()
        if is_owner(principal, record):
            return record
        if await member_organization(principal) != organization_id:
            raise not_found()  # não revela a existência de Organizations de outros donos
        return record

    def check_version(record: ResourceRecord, version: str) -> None:
        if str(record.resource_version) != version:
            raise conflict()

    def require_billing_account(principal: Principal, billing_account_id: str) -> None:
        """A Billing Account deve existir, pertencer ao solicitante e estar ativa (`Ready`)."""
        ready = deps.billing_accounts.is_ready_billing_account(
            billing_account_id, principal.subject
        )
        if not ready:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "BillingAccountNotReady",
                "A Billing Account informada não existe ou não está ativa (Ready).",
            )

    def admission_for(
        principal: Principal,
        operation: Literal["create", "update", "delete"],
        resource_id: str,
        idempotency_key: str | None,
        content: Mapping[str, Any],
        **extra: Any,
    ) -> Admission:
        return Admission(
            operation=operation,
            resource_id=resource_id,
            requested_by=principal.subject,
            correlation_id=deps.identifiers(),
            request_digest=request_digest(content),
            now=deps.clock(),
            message_id=deps.identifiers(),
            idempotency_key=checked_idempotency_key(idempotency_key),
            **extra,
        )

    # ------------------------------------------------------------ organizations

    @app.post(
        "/v1/ipm/organizations",
        status_code=201,
        response_model=generated.Organization,
        response_model_exclude_none=True,
    )
    async def create_organization(
        body: generated.OrganizationCreateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.Organization:
        require(principal, permissions.ORGANIZATION_CREATE)
        quota: int | None = None
        if not principal.is_operator:
            if not await deps.email_verifier.is_verified(principal):
                raise ApiError(
                    HTTPStatus.FORBIDDEN,
                    "EmailNotVerified",
                    "O e-mail do solicitante não foi verificado.",
                )
            quota = deps.settings.api.organization_quota
        specification: dict[str, Any] = {"name": body.name, "platformAccess": "granted"}
        if body.billing_account_id is not None:
            if not principal.is_operator:
                require_billing_account(principal, body.billing_account_id)
            specification["billingAccountId"] = body.billing_account_id
        new_organization_id = deps.identifiers()
        admission = admission_for(
            principal,
            "create",
            new_organization_id,
            idempotency_key,
            {"operation": "create", "specification": specification},
            specification=specification,
            quota_limit=quota,
        )
        record = await admit(deps.admissions, admission, user_access=deps.user_access_data)
        return organization_view(record)

    @app.get(
        "/v1/ipm/organizations/{organization_id}",
        response_model=generated.Organization,
        response_model_exclude_none=True,
    )
    async def get_organization(
        organization_id: str, principal: Authenticated
    ) -> generated.Organization:
        require(principal, permissions.ORGANIZATION_GET)
        return organization_view(await owned_organization(principal, organization_id))

    @app.get(
        "/v1/ipm/organizations",
        response_model=generated.OrganizationList,
        response_model_exclude_none=True,
    )
    async def list_organizations(
        principal: Authenticated,
        limit: Annotated[int, Query(ge=1, le=MAXIMUM_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        cursor: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9_-]{1,512}$")] = None,
    ) -> generated.OrganizationList:
        require(principal, permissions.ORGANIZATION_LIST)
        owner = None if principal.is_operator else principal.subject
        records = await deps.repository.list_organizations(
            owner=owner, after=cursor, limit=limit + 1
        )
        if owner is not None and not records and cursor is None:
            # Sem Organizations próprias, o solicitante pode ser usuário de uma (decisão 0077).
            member_of = await member_organization(principal)
            record = await deps.repository.get_organization(member_of) if member_of else None
            records = [record] if record is not None else []
        page = records[:limit]
        payload: dict[str, Any] = {
            "items": [
                organization_view(record).model_dump(mode="json", exclude_none=True)
                for record in page
            ]
        }
        if len(records) > limit:
            payload["nextCursor"] = page[-1].resource_id
        return generated.OrganizationList.model_validate(payload)

    @app.patch(
        "/v1/ipm/organizations/{organization_id}",
        status_code=200,
        response_model=generated.Organization,
        response_model_exclude_none=True,
    )
    async def update_organization(
        organization_id: str,
        body: generated.OrganizationUpdateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.Organization:
        require(principal, permissions.ORGANIZATION_UPDATE)
        record = await owned_organization(principal, organization_id)
        if not is_owner(principal, record):
            raise not_found()
        if not body.resource_version.isdigit():
            raise bad_request("resourceVersion deve ser numérico.", field="resourceVersion")
        specification: dict[str, Any] = {}
        if body.name is not None:
            specification["name"] = body.name
        if body.platform_access is not None:
            specification["platformAccess"] = body.platform_access.value
        if body.deletion_protection is not None:
            specification["deletionProtection"] = body.deletion_protection
        if body.billing_account_id is not None:
            if not principal.is_operator:
                require_billing_account(principal, body.billing_account_id)
            specification["billingAccountId"] = body.billing_account_id
        reconciliation = body.reconciliation.value if body.reconciliation is not None else None
        if not specification and reconciliation is None:
            raise bad_request("Informe ao menos um campo a alterar.")
        # Acesso à plataforma e controle da reconciliação são privilégios de operador.
        if (
            "platformAccess" in specification or reconciliation is not None
        ) and not principal.is_operator:
            raise forbidden()
        check_version(record, body.resource_version)
        content: dict[str, Any] = {
            "operation": "update",
            "resourceId": organization_id,
            "resourceVersion": body.resource_version,
        }
        if specification:
            content["specification"] = specification
        if reconciliation is not None:
            content["reconciliation"] = reconciliation
        admission = admission_for(
            principal,
            "update",
            organization_id,
            idempotency_key,
            content,
            resource_version=int(body.resource_version),
            specification=specification or None,
            reconciliation=reconciliation,
        )
        updated_record = await admit(deps.admissions, admission)
        return organization_view(updated_record)

    @app.delete(
        "/v1/ipm/organizations/{organization_id}",
        status_code=202,
        response_model=generated.Organization,
        response_model_exclude_none=True,
    )
    async def delete_organization(
        organization_id: str,
        principal: Authenticated,
        resource_version: VersionQuery,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.Organization:
        require(principal, permissions.ORGANIZATION_DELETE)
        record = await owned_organization(principal, organization_id)
        if not is_owner(principal, record):
            raise not_found()
        check_version(record, resource_version)
        if record.desired.get("deletionProtection", True) is not False:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "DeletionProtected",
                "A Organization está protegida contra exclusão. Desproteja-a antes de excluir.",
            )
        # Só vazia: a remoção no provedor apagaria os usuários junto (decisão 0077). A repetição
        # de uma remoção já aceita não pergunta de novo.
        if record.lifecycle == "present" and deps.dependents.has_dependents(organization_id):
            raise ApiError(
                HTTPStatus.CONFLICT,
                "ResourcesAttached",
                "A Organization ainda tem usuários. Remova-os antes de excluir a Organization.",
            )
        admission = admission_for(
            principal,
            "delete",
            organization_id,
            idempotency_key,
            {
                "operation": "delete",
                "resourceId": organization_id,
                "resourceVersion": resource_version,
            },
            resource_version=int(resource_version),
        )
        deleted_record = await admit(deps.admissions, admission)
        return organization_view(deleted_record)
