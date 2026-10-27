"""Aplicação HTTP da API de Billing Account (decisões 0082, 0098 e 0100).

A API autentica, autoriza, valida e **admite a escrita de forma síncrona**: numa transação do SSOT
grava a Billing Account e o `desired` no outbox (o Publisher publica depois). Não há Operation:
`POST` responde `201`, `PATCH` responde `200` e `DELETE` responde `202`, todos com o `Resource`. A
Billing Account é dado do SSOT (nada externo a materializa hoje): nasce `Ready` e o `DELETE` remove
a linha.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Annotated, Any, Protocol

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from bsm_account.api.domain import principal as permissions
from bsm_account.api.domain.admission import Admission
from bsm_account.api.domain.errors import (
    ApiError,
    bad_request,
    conflict,
    forbidden,
    not_found,
    unauthorized,
)
from bsm_account.api.domain.principal import Principal
from bsm_account.api.domain.records import ResourceRecord
from bsm_account.api.domain.requests import checked_idempotency_key, request_digest
from bsm_account.api.domain.views import account_view
from bsm_account.api.http.admission import admit
from bsm_account.api.http.health_routes import register_health_routes
from bsm_account.api.http.ports import (
    AdmissionStore,
    EmailVerifier,
    Organizations,
    Repository,
)
from bsm_account.api.http.trace_context import TraceContextMiddleware
from bsm_account.api.settings import AccountApiSettings
from bsm_account.common.contracts import generated
from bsm_account.common.ids import new_identifier, utc_now
from bsm_account.common.logging_config import bind_context

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 50
MAXIMUM_PAGE_SIZE = 200
RESOURCE_ID_PATTERN = r"^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$"


class Authenticator(Protocol):
    async def verify(self, token: str) -> Principal: ...


@dataclass(frozen=True)
class Dependencies:
    settings: AccountApiSettings
    authenticator: Authenticator
    email_verifier: EmailVerifier
    repository: Repository
    store: AdmissionStore
    organizations: Organizations
    identifiers: Callable[[], str] = new_identifier
    is_synced: Callable[[], bool] = lambda: True


def _contacts(items: list[generated.BillingContact]) -> list[str]:
    return [str(item.root) for item in items]


def _error_response(error: ApiError) -> JSONResponse:
    content: dict[str, Any] = {"errorCode": error.error_code, "message": error.message}
    if error.field is not None:
        content["field"] = error.field
    return JSONResponse(
        content=generated.ApiError.model_validate(content).model_dump(
            mode="json", exclude_none=True
        ),
        status_code=error.status,
        headers=error.headers,
    )


async def authenticate(request: Request) -> Principal:
    deps: Dependencies = request.app.state.dependencies
    authorization = request.headers.get("authorization")
    if not authorization or not authorization.startswith("Bearer "):
        raise unauthorized()
    token = authorization.removeprefix("Bearer ").strip()
    principal = await deps.authenticator.verify(token)
    bind_context(requested_by=principal.subject)
    return principal


Authenticated = Annotated[Principal, Depends(authenticate)]
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]
VersionQuery = Annotated[str, Query(alias="resourceVersion")]


def _require(principal: Principal, permission: str) -> None:
    if not principal.has_permission(permission):
        raise forbidden()


async def _owned_account(
    repository: Repository, principal: Principal, account_id: str
) -> ResourceRecord:
    record = await repository.get_account(account_id)
    if record is None:
        raise not_found()
    if not principal.is_operator and record.desired.get("ownerAccountId") != principal.subject:
        raise not_found()
    return record


def _check_version(record: ResourceRecord, version: str) -> None:
    if str(record.resource_version) != version:
        raise conflict()


def create_app(deps: Dependencies) -> FastAPI:
    app = FastAPI(
        title="bsm-account-api",
        description="API HTTP de bsm.account (Billing Account no SSOT).",
        version="1.0",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    app.state.dependencies = deps
    app.add_middleware(TraceContextMiddleware)
    register_health_routes(app, is_ready=lambda: deps.is_synced())

    # -------------------------------------------------------- tratamento de erro

    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, error: ApiError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return _error_response(error)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(  # pyright: ignore[reportUnusedFunction]
        _: Request, error: RequestValidationError
    ) -> JSONResponse:
        first = error.errors()[0]
        field = ".".join(str(part) for part in first["loc"][1:]) or None
        return _error_response(bad_request(f"Campo inválido: {first['msg']}", field=field))

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, error: Exception) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        logger.error("unexpected error", exc_info=error)
        return _error_response(
            ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "InternalError", "Erro interno.")
        )

    # ---------------------------------------------------------------------- rotas

    @app.get(
        "/v1/bsm/accounts/{account_id}",
        response_model=generated.BillingAccount,
        response_model_exclude_none=True,
    )
    async def get_account(account_id: str, principal: Authenticated) -> generated.BillingAccount:
        _require(principal, permissions.ACCOUNT_GET)
        record = await _owned_account(deps.repository, principal, account_id)
        return account_view(record)

    @app.get(
        "/v1/bsm/accounts",
        response_model=generated.BillingAccountList,
        response_model_exclude_none=True,
    )
    async def list_accounts(
        principal: Authenticated,
        limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAXIMUM_PAGE_SIZE),
        cursor: str | None = Query(None, pattern=RESOURCE_ID_PATTERN),
    ) -> generated.BillingAccountList:
        _require(principal, permissions.ACCOUNT_LIST)
        owner = None if principal.is_operator else principal.subject
        page = await deps.repository.list_accounts(owner=owner, after=cursor, limit=limit)
        payload: dict[str, Any] = {"items": [account_view(record) for record in page]}
        if len(page) == limit:
            payload["nextCursor"] = page[-1].resource_id
        return generated.BillingAccountList.model_validate(payload)

    @app.post(
        "/v1/bsm/accounts",
        status_code=201,
        response_model=generated.BillingAccount,
        response_model_exclude_none=True,
    )
    async def create_account(
        body: generated.BillingAccountCreateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.BillingAccount:
        _require(principal, permissions.ACCOUNT_CREATE)
        quota_limit: int | None = None
        if not principal.is_operator:
            if not await deps.email_verifier.is_verified(principal):
                raise ApiError(
                    HTTPStatus.FORBIDDEN,
                    "EmailNotVerified",
                    "O e-mail do solicitante não foi verificado.",
                )
            quota_limit = deps.settings.api.account_quota

        specification = {
            "displayName": body.display_name,
            "billingCurrency": body.billing_currency.value,
            "billingContacts": _contacts(body.billing_contacts),
        }
        resource_id = deps.identifiers()
        key = checked_idempotency_key(idempotency_key)
        digest = request_digest({"operation": "create", "specification": specification})
        admission = Admission(
            operation="create",
            resource_id=resource_id,
            requested_by=principal.subject,
            correlation_id=deps.identifiers(),
            request_digest=digest,
            now=utc_now(),
            message_id=deps.identifiers(),
            idempotency_key=key,
            specification=specification,
            quota_limit=quota_limit,
        )
        record = await admit(deps.store, admission)
        return account_view(record)

    @app.patch(
        "/v1/bsm/accounts/{account_id}",
        status_code=200,
        response_model=generated.BillingAccount,
        response_model_exclude_none=True,
    )
    async def update_account(
        account_id: str,
        body: generated.BillingAccountUpdateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.BillingAccount:
        _require(principal, permissions.ACCOUNT_UPDATE)
        record = await _owned_account(deps.repository, principal, account_id)
        if not body.resource_version.isdigit():
            raise bad_request("resourceVersion deve ser numérico.", field="resourceVersion")
        specification: dict[str, Any] = {}
        if body.display_name is not None:
            specification["displayName"] = body.display_name
        if body.billing_contacts is not None:
            specification["billingContacts"] = _contacts(body.billing_contacts)
        if body.deletion_protection is not None:
            specification["deletionProtection"] = body.deletion_protection
        reconciliation = body.reconciliation.value if body.reconciliation is not None else None
        if not specification and reconciliation is None:
            raise bad_request("Informe ao menos um campo a alterar.")
        if reconciliation is not None and not principal.is_operator:
            raise forbidden()
        _check_version(record, body.resource_version)

        content: dict[str, Any] = {
            "operation": "update",
            "resourceId": account_id,
            "resourceVersion": body.resource_version,
        }
        if specification:
            content["specification"] = specification
        if reconciliation is not None:
            content["reconciliation"] = reconciliation

        key = checked_idempotency_key(idempotency_key)
        digest = request_digest(content)
        admission = Admission(
            operation="update",
            resource_id=account_id,
            resource_version=int(body.resource_version),
            requested_by=principal.subject,
            correlation_id=deps.identifiers(),
            request_digest=digest,
            now=utc_now(),
            message_id=deps.identifiers(),
            idempotency_key=key,
            specification=specification or None,
            reconciliation=reconciliation,
        )
        record = await admit(deps.store, admission)
        return account_view(record)

    @app.delete(
        "/v1/bsm/accounts/{account_id}",
        status_code=202,
        response_model=generated.BillingAccount,
        response_model_exclude_none=True,
    )
    async def delete_account(
        account_id: str,
        principal: Authenticated,
        resource_version: VersionQuery,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.BillingAccount:
        _require(principal, permissions.ACCOUNT_DELETE)
        record = await _owned_account(deps.repository, principal, account_id)
        if not resource_version.isdigit():
            raise bad_request("resourceVersion deve ser numérico.", field="resourceVersion")
        _check_version(record, resource_version)

        if record.desired.get("deletionProtection", True) is not False:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "DeletionProtected",
                "A Billing Account está protegida contra exclusão. "
                "Desative deletionProtection antes de remover.",
                field="deletionProtection",
            )

        if deps.organizations.has_attached_organizations(account_id):
            raise ApiError(
                HTTPStatus.CONFLICT,
                "ResourcesAttached",
                "A Billing Account tem Organizations vinculadas. Remova-as antes.",
            )

        key = checked_idempotency_key(idempotency_key)
        digest = request_digest({
            "operation": "delete",
            "resourceId": account_id,
            "resourceVersion": resource_version,
        })
        admission = Admission(
            operation="delete",
            resource_id=account_id,
            resource_version=int(resource_version),
            requested_by=principal.subject,
            correlation_id=deps.identifiers(),
            request_digest=digest,
            now=utc_now(),
            message_id=deps.identifiers(),
            idempotency_key=key,
        )
        record = await admit(deps.store, admission)
        return account_view(record)

    return app
