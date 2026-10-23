"""Aplicação HTTP do Receiver (`docs/RESOURCE-CONTROL-LOOP.md` §6.1).

O Receiver autentica, autoriza, valida, gera as identidades e **publica `requested`**; ele não
escreve no SSOT. As leituras vêm das views do SSOT. Toda escrita responde `202 Accepted` com o
`operationId`.
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

from bsm_account.common.contracts import generated
from bsm_account.common.ids import new_identifier, utc_now
from bsm_account.common.logging_config import bind_context
from bsm_account.common.ports import Publisher
from bsm_account.receiver.domain import principal as roles
from bsm_account.receiver.domain.errors import (
    ApiError,
    bad_request,
    forbidden,
    not_found,
    unauthorized,
)
from bsm_account.receiver.domain.organizations import OrganizationsCheckError
from bsm_account.receiver.domain.principal import Principal
from bsm_account.receiver.domain.records import ResourceRecord
from bsm_account.receiver.domain.views import account_view, operation_view
from bsm_account.receiver.http.health_routes import register_health_routes
from bsm_account.receiver.http.ports import Organizations, Repository
from bsm_account.receiver.http.submission import submit
from bsm_account.receiver.http.trace_context import TraceContextMiddleware
from bsm_account.receiver.settings import ApiSettings

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
    organizations: Organizations
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
    app = FastAPI(title="smarkee bsm account api", docs_url=None, redoc_url=None, openapi_url=None)
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


def _contacts(items: list[generated.BillingContact]) -> list[str]:
    values = [str(item.root) for item in items]
    if len(set(values)) != len(values):
        raise bad_request(
            "Os e-mails de contato financeiro não podem se repetir.",
            field="billingContacts",
        )
    return values


def _register_routes(app: FastAPI, deps: Dependencies) -> None:
    def require(principal: Principal, role: str) -> None:
        if not principal.has_role(role):
            raise forbidden()

    def is_owner(principal: Principal, record: ResourceRecord) -> bool:
        return principal.is_operator or record.desired.get("ownerAccountId") == principal.subject

    async def owned_account(principal: Principal, account_id: str) -> ResourceRecord:
        """A Billing Account, se o solicitante é o dono ou o operador."""
        record = await deps.repository.get_account(account_id)
        if record is None or not is_owner(principal, record):
            raise not_found()  # não revela a existência de Billing Accounts de outros donos
        return record

    def check_version(record: ResourceRecord, version: str) -> None:
        if str(record.resource_version) != version:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Conflict",
                "O recurso mudou desde a leitura. Leia de novo e repita o pedido.",
            )

    # ------------------------------------------------------------ accounts

    @app.post(
        "/v1/bsm/accounts",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def create_account(
        body: generated.BillingAccountCreateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ApiAcceptedResponse:
        require(principal, roles.ACCOUNT_CREATE)
        if not principal.is_operator and not await deps.email_verifier.is_verified(principal):
            raise ApiError(
                HTTPStatus.FORBIDDEN,
                "EmailNotVerified",
                "O e-mail do solicitante não foi verificado.",
            )
        contacts = _contacts(body.billing_contacts)
        specification = {
            "displayName": body.display_name,
            "billingCurrency": body.billing_currency.value,
            "billingContacts": contacts,
        }
        new_account_id = deps.identifiers()
        return await submit(
            deps,
            resource_id=new_account_id,
            operation="create",
            requested_by=principal.subject,
            digest_content={"operation": "create", "specification": specification},
            extra_data={"specification": specification},
            idempotency_key=idempotency_key,
        )

    @app.get(
        "/v1/bsm/accounts/{account_id}",
        response_model=generated.BillingAccount,
        response_model_exclude_none=True,
    )
    async def get_account(account_id: str, principal: Authenticated) -> generated.BillingAccount:
        require(principal, roles.ACCOUNT_GET)
        return account_view(await owned_account(principal, account_id))

    @app.get(
        "/v1/bsm/accounts",
        response_model=generated.BillingAccountList,
        response_model_exclude_none=True,
    )
    async def list_accounts(
        principal: Authenticated,
        limit: Annotated[int, Query(ge=1, le=MAXIMUM_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        cursor: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9_-]{1,512}$")] = None,
    ) -> generated.BillingAccountList:
        require(principal, roles.ACCOUNT_LIST)
        owner = None if principal.is_operator else principal.subject
        records = await deps.repository.list_accounts(owner=owner, after=cursor, limit=limit + 1)
        page = records[:limit]
        payload: dict[str, Any] = {
            "items": [
                account_view(record).model_dump(mode="json", exclude_none=True) for record in page
            ]
        }
        if len(records) > limit:
            payload["nextCursor"] = page[-1].resource_id
        return generated.BillingAccountList.model_validate(payload)

    @app.patch(
        "/v1/bsm/accounts/{account_id}",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def update_account(
        account_id: str,
        body: generated.BillingAccountUpdateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ApiAcceptedResponse:
        require(principal, roles.ACCOUNT_UPDATE)
        record = await owned_account(principal, account_id)
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
        # Controle da reconciliação é privilégio de operador.
        if reconciliation is not None and not principal.is_operator:
            raise forbidden()
        check_version(record, body.resource_version)
        content: dict[str, Any] = {
            "operation": "update",
            "resourceId": account_id,
            "resourceVersion": body.resource_version,
        }
        data: dict[str, Any] = {"resourceVersion": body.resource_version}
        if specification:
            content["specification"] = data["specification"] = specification
        if reconciliation is not None:
            content["reconciliation"] = data["reconciliation"] = reconciliation
        return await submit(
            deps,
            resource_id=account_id,
            operation="update",
            requested_by=principal.subject,
            digest_content=content,
            extra_data=data,
            idempotency_key=idempotency_key,
        )

    @app.delete(
        "/v1/bsm/accounts/{account_id}",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def delete_account(
        account_id: str,
        principal: Authenticated,
        resource_version: VersionQuery,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ApiAcceptedResponse:
        require(principal, roles.ACCOUNT_DELETE)
        record = await owned_account(principal, account_id)
        check_version(record, resource_version)
        if record.desired.get("deletionProtection", True) is not False:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "DeletionProtected",
                "A Billing Account está protegida contra exclusão. Desproteja-a antes de excluir.",
            )
        if not idempotency_key:
            try:
                has_organizations = await deps.organizations.has_organizations(
                    account_id, principal.access_token
                )
            except OrganizationsCheckError as error:
                if error.retryable:
                    raise ApiError(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        "OrganizationsUnavailable",
                        "Não foi possível consultar as Organizations agora. Tente de novo.",
                        headers={"Retry-After": RETRY_AFTER_SECONDS},
                    ) from None
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "ResourcesNotVerifiable",
                    "Não foi possível confirmar as Organizations vinculadas à Billing Account.",
                ) from None
            if has_organizations:
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "ResourcesAttached",
                    "A Billing Account tem Organizations vinculadas. Remova-as antes.",
                )
        return await submit(
            deps,
            resource_id=account_id,
            operation="delete",
            requested_by=principal.subject,
            digest_content={
                "operation": "delete",
                "resourceId": account_id,
                "resourceVersion": resource_version,
            },
            extra_data={"resourceVersion": resource_version},
            idempotency_key=idempotency_key,
        )

    # ------------------------------------------------------------ operations e saúde

    @app.get(
        "/v1/bsm/accounts/{account_id}/operations/{operation_id}",
        response_model=generated.Operation,
        response_model_exclude_none=True,
    )
    async def get_operation(
        account_id: str, operation_id: str, principal: Authenticated
    ) -> generated.Operation:
        record = await deps.repository.find_operation(operation_id)
        # Só o solicitante e os operadores leem a Operation, e ela deve ser do recurso da rota.
        if (
            record is None
            or record.resource_id != account_id
            or not (principal.is_operator or record.requested_by == principal.subject)
        ):
            raise not_found()
        return operation_view(record)
