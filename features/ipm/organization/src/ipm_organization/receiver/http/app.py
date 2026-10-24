"""Aplicação HTTP do Receiver (`docs/RESOURCE-CONTROL-LOOP.md` §6.1).

O Receiver autentica, autoriza, valida, gera as identidades e **publica `requested`**; ele não
escreve no SSOT e não tem credencial de escrita no provedor de identidade. As leituras vêm das
views do SSOT. Toda escrita responde `202 Accepted` com o `operationId`.

Quem age numa Organization (decisão 0077): o dono (root), o operador e os usuários dela, estes
reconhecidos pelo Receiver do User com o token de quem pede (decisão 0040). A Organization só é
removida vazia, sem usuários.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any, Protocol

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ipm_organization.common.contracts import generated
from ipm_organization.common.ids import new_identifier, utc_now
from ipm_organization.common.logging_config import bind_context
from ipm_organization.common.ports import Publisher
from ipm_organization.receiver.domain import principal as permissions
from ipm_organization.receiver.domain.errors import (
    ApiError,
    bad_request,
    forbidden,
    not_found,
    unauthorized,
)
from ipm_organization.receiver.domain.principal import Principal
from ipm_organization.receiver.domain.records import ResourceRecord
from ipm_organization.receiver.domain.users import BillingAccountCheckError, UsersCheckError
from ipm_organization.receiver.domain.views import operation_view, organization_view
from ipm_organization.receiver.http.health_routes import register_health_routes
from ipm_organization.receiver.http.ports import Repository, Users
from ipm_organization.receiver.http.submission import submit
from ipm_organization.receiver.http.trace_context import TraceContextMiddleware
from ipm_organization.receiver.settings import ApiSettings

logger = logging.getLogger(__name__)

RETRY_AFTER_SECONDS = "5"
DEFAULT_PAGE_SIZE = 50
MAXIMUM_PAGE_SIZE = 200


class Authenticator(Protocol):
    async def verify(self, token: str) -> Principal: ...


class EmailVerifier(Protocol):
    async def is_verified(self, principal: Principal) -> bool: ...


@dataclass(frozen=True)
class Dependencies:
    settings: ApiSettings
    authenticator: Authenticator
    email_verifier: EmailVerifier
    repository: Repository
    users: Users
    publisher: Publisher
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

    def users_unverifiable(error: UsersCheckError) -> ApiError:
        if error.retryable:
            return ApiError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "UsersUnavailable",
                "Não foi possível consultar os usuários da Organization agora. Tente de novo.",
                headers={"Retry-After": RETRY_AFTER_SECONDS},
            )
        return ApiError(
            HTTPStatus.CONFLICT,
            "ResourcesNotVerifiable",
            "Não foi possível confirmar os usuários da Organization.",
        )

    async def member_organization(principal: Principal) -> str | None:
        """A Organization de que o solicitante é usuário, pelo Receiver do User (decisão 0077)."""
        try:
            return await deps.users.organization_of(principal.subject, principal.access_token)
        except UsersCheckError as error:
            raise users_unverifiable(error) from None

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
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Conflict",
                "O recurso mudou desde a leitura. Leia de novo e repita o pedido.",
            )

    async def require_billing_account(principal: Principal, billing_account_id: str) -> None:
        """A Billing Account deve existir, pertencer ao solicitante e estar ativa (`Ready`)."""
        try:
            ready = await deps.users.is_ready_billing_account(
                billing_account_id, principal.access_token
            )
        except BillingAccountCheckError as error:
            if error.retryable:
                raise ApiError(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "BillingAccountsUnavailable",
                    "Não foi possível consultar a Billing Account agora. Tente de novo.",
                    headers={"Retry-After": RETRY_AFTER_SECONDS},
                ) from None
            raise ApiError(
                HTTPStatus.CONFLICT,
                "ResourcesNotVerifiable",
                "Não foi possível confirmar a Billing Account.",
            ) from None
        if not ready:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "BillingAccountNotReady",
                "A Billing Account informada não existe ou não está ativa (Ready).",
            )

    # ------------------------------------------------------------ organizations

    @app.post(
        "/v1/ipm/organizations",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def create_organization(
        body: generated.OrganizationCreateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ApiAcceptedResponse:
        require(principal, permissions.ORGANIZATION_CREATE)
        quota: int | None = None
        if not principal.is_operator:
            if not await deps.email_verifier.is_verified(principal):
                raise ApiError(
                    HTTPStatus.FORBIDDEN,
                    "EmailNotVerified",
                    "O e-mail do solicitante não foi verificado.",
                )
            quota = deps.settings.organization_quota
            if await deps.repository.count_organizations_owned_by(principal.subject) >= quota:
                raise ApiError(
                    HTTPStatus.FORBIDDEN, "QuotaExceeded", "Limite de Organizations atingido."
                )
        specification: dict[str, Any] = {"name": body.name, "platformAccess": "granted"}
        if body.billing_account_id is not None:
            await require_billing_account(principal, body.billing_account_id)
            specification["billingAccountId"] = body.billing_account_id
        new_organization_id = deps.identifiers()
        return await submit(
            deps,
            log_context={"organization_id": new_organization_id},
            resource_id=new_organization_id,
            operation="create",
            requested_by=principal.subject,
            digest_content={"operation": "create", "specification": specification},
            extra_data={
                "specification": specification,
                **({"ownerQuotaLimit": quota} if quota is not None else {}),
            },
            idempotency_key=idempotency_key,
        )

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
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def update_organization(
        organization_id: str,
        body: generated.OrganizationUpdateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ApiAcceptedResponse:
        require(principal, permissions.ORGANIZATION_UPDATE)
        record = await owned_organization(principal, organization_id)
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
            await require_billing_account(principal, body.billing_account_id)
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
        data: dict[str, Any] = {"resourceVersion": body.resource_version}
        if specification:
            content["specification"] = data["specification"] = specification
        if reconciliation is not None:
            content["reconciliation"] = data["reconciliation"] = reconciliation
        return await submit(
            deps,
            log_context={"organization_id": organization_id},
            resource_id=organization_id,
            operation="update",
            requested_by=principal.subject,
            digest_content=content,
            extra_data=data,
            idempotency_key=idempotency_key,
        )

    @app.delete(
        "/v1/ipm/organizations/{organization_id}",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def delete_organization(
        organization_id: str,
        principal: Authenticated,
        resource_version: VersionQuery,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ApiAcceptedResponse:
        require(principal, permissions.ORGANIZATION_DELETE)
        record = await owned_organization(principal, organization_id)
        check_version(record, resource_version)
        if record.desired.get("deletionProtection", True) is not False:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "DeletionProtected",
                "A Organization está protegida contra exclusão. Desproteja-a antes de excluir.",
            )
        # Só vazia: a remoção no provedor apagaria os usuários junto (decisão 0077). A repetição
        # de uma remoção já aceita não pergunta de novo.
        try:
            attached = record.lifecycle == "present" and await deps.users.has_users(
                organization_id, principal.access_token
            )
        except UsersCheckError as error:
            raise users_unverifiable(error) from None
        if attached:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "ResourcesAttached",
                "A Organization ainda tem usuários. Remova-os antes de excluir a Organization.",
            )
        return await submit(
            deps,
            log_context={"organization_id": organization_id},
            resource_id=organization_id,
            operation="delete",
            requested_by=principal.subject,
            digest_content={
                "operation": "delete",
                "resourceId": organization_id,
                "resourceVersion": resource_version,
            },
            extra_data={"resourceVersion": resource_version},
            idempotency_key=idempotency_key,
        )

    # ------------------------------------------------------------ operations e saúde

    @app.get(
        "/v1/ipm/organizations/{organization_id}/operations/{operation_id}",
        response_model=generated.Operation,
        response_model_exclude_none=True,
    )
    async def get_operation(
        organization_id: str, operation_id: str, principal: Authenticated
    ) -> generated.Operation:
        record = await deps.repository.find_operation(operation_id)
        # Só o solicitante e os operadores leem a Operation, e ela deve ser do recurso da rota.
        if (
            record is None
            or record.resource_id != organization_id
            or not (principal.is_operator or record.requested_by == principal.subject)
        ):
            raise not_found()
        return operation_view(record)
