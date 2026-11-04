"""Aplicação HTTP da API de Payment (`bsm.payment`, decisões 0098 e 0100).

A API autentica, autoriza, valida e **admite a escrita de forma síncrona**: numa transação do SSOT
grava o recurso `bsm.payment` (com `phase = Pending` na criação) e o `desired` no outbox. O
Publisher publica depois e o Controller reconcilia no gateway de pagamento externo.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Annotated, Any, Protocol

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from bsm_payment.api.domain import principal as permissions
from bsm_payment.api.domain.admission import Admission
from bsm_payment.api.domain.errors import (
    ApiError,
    bad_request,
    conflict,
    forbidden,
    not_found,
    unauthorized,
)
from bsm_payment.api.domain.principal import Principal
from bsm_payment.api.domain.records import ResourceRecord
from bsm_payment.api.domain.requests import checked_idempotency_key, request_digest
from bsm_payment.api.domain.views import payment_view
from bsm_payment.api.http.admission import admit
from bsm_payment.api.http.health_routes import register_health_routes
from bsm_payment.api.http.ports import (
    AdmissionStore,
    BillingAccounts,
    EmailVerifier,
    Repository,
)
from bsm_payment.api.http.trace_context import TraceContextMiddleware
from bsm_payment.api.settings import PaymentApiSettings
from bsm_payment.common.contracts import generated
from bsm_payment.common.ids import new_identifier, utc_now
from bsm_payment.common.logging_config import bind_context

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 50
MAXIMUM_PAGE_SIZE = 200
RESOURCE_ID_PATTERN = r"^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$"


class Authenticator(Protocol):
    async def verify(self, token: str) -> Principal: ...


@dataclass(frozen=True)
class Dependencies:
    settings: PaymentApiSettings
    authenticator: Authenticator
    email_verifier: EmailVerifier
    repository: Repository
    store: AdmissionStore
    billing_accounts: BillingAccounts
    identifiers: Callable[[], str] = new_identifier
    is_synced: Callable[[], bool] = lambda: True


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


async def _owned_payment(
    repository: Repository, principal: Principal, payment_id: str
) -> ResourceRecord:
    record = await repository.get_payment(payment_id)
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
        title="bsm-payment-api",
        description=(
            "API HTTP de bsm.payment (Método de Pagamento reconciliado com gateway externo)."
        ),
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
        "/v1/bsm/payments/{payment_id}",
        response_model=generated.Payment,
        response_model_exclude_none=True,
    )
    async def get_payment(payment_id: str, principal: Authenticated) -> generated.Payment:
        _require(principal, permissions.PAYMENT_GET)
        record = await _owned_payment(deps.repository, principal, payment_id)
        return payment_view(record)

    @app.get(
        "/v1/bsm/payments",
        response_model=generated.PaymentList,
        response_model_exclude_none=True,
    )
    async def list_payments(
        principal: Authenticated,
        limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAXIMUM_PAGE_SIZE),
        cursor: str | None = Query(None, pattern=RESOURCE_ID_PATTERN),
    ) -> generated.PaymentList:
        _require(principal, permissions.PAYMENT_LIST)
        owner = None if principal.is_operator else principal.subject
        page = await deps.repository.list_payments(owner=owner, after=cursor, limit=limit)
        payload: dict[str, Any] = {"items": [payment_view(record) for record in page]}
        if len(page) == limit:
            payload["nextCursor"] = page[-1].resource_id
        return generated.PaymentList.model_validate(payload)

    @app.post(
        "/v1/bsm/payments",
        status_code=201,
        response_model=generated.Payment,
        response_model_exclude_none=True,
    )
    async def create_payment(
        body: generated.PaymentCreateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.Payment:
        _require(principal, permissions.PAYMENT_CREATE)
        customer_account_id = body.customer_account_id
        quota_limit: int | None = None
        if not principal.is_operator:
            if customer_account_id != principal.subject:
                raise forbidden(
                    "O solicitante só pode criar métodos de pagamento "
                    "para a sua própria Customer Account."
                )
            if not await deps.email_verifier.is_verified(principal):
                raise ApiError(
                    HTTPStatus.FORBIDDEN,
                    "EmailNotVerified",
                    "O e-mail do solicitante não foi verificado.",
                )
            quota_limit = deps.settings.api.payment_quota

        specification = {
            "customerAccountId": customer_account_id,
            "displayName": body.display_name,
            "provider": body.provider.value,
            "methodType": body.method_type.value,
            "providerToken": body.provider_token,
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
        return payment_view(record)

    @app.patch(
        "/v1/bsm/payments/{payment_id}",
        status_code=200,
        response_model=generated.Payment,
        response_model_exclude_none=True,
    )
    async def update_payment(
        payment_id: str,
        body: generated.PaymentUpdateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.Payment:
        _require(principal, permissions.PAYMENT_UPDATE)
        record = await _owned_payment(deps.repository, principal, payment_id)
        if not body.resource_version.isdigit():
            raise bad_request("resourceVersion deve ser numérico.", field="resourceVersion")
        specification: dict[str, Any] = {}
        if body.display_name is not None:
            specification["displayName"] = body.display_name
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
            "resourceId": payment_id,
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
            resource_id=payment_id,
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
        return payment_view(record)

    @app.delete(
        "/v1/bsm/payments/{payment_id}",
        status_code=202,
        response_model=generated.Payment,
        response_model_exclude_none=True,
    )
    async def delete_payment(
        payment_id: str,
        principal: Authenticated,
        resource_version: VersionQuery,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.Payment:
        _require(principal, permissions.PAYMENT_DELETE)
        record = await _owned_payment(deps.repository, principal, payment_id)
        if not resource_version.isdigit():
            raise bad_request("resourceVersion deve ser numérico.", field="resourceVersion")
        _check_version(record, resource_version)

        if record.desired.get("deletionProtection", True) is not False:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "DeletionProtected",
                "O método de pagamento está protegido contra exclusão. "
                "Desative deletionProtection antes de remover.",
                field="deletionProtection",
            )

        if deps.billing_accounts.has_attached_billing_accounts(payment_id):
            raise ApiError(
                HTTPStatus.CONFLICT,
                "ResourcesAttached",
                "O método de pagamento está vinculado a uma Billing Account ativa. "
                "Substitua-o ou remova a Billing Account antes.",
            )

        key = checked_idempotency_key(idempotency_key)
        digest = request_digest(
            {
                "operation": "delete",
                "resourceId": payment_id,
                "resourceVersion": resource_version,
            }
        )
        admission = Admission(
            operation="delete",
            resource_id=payment_id,
            resource_version=int(resource_version),
            requested_by=principal.subject,
            correlation_id=deps.identifiers(),
            request_digest=digest,
            now=utc_now(),
            message_id=deps.identifiers(),
            idempotency_key=key,
        )
        record = await admit(deps.store, admission)
        return payment_view(record)

    return app
