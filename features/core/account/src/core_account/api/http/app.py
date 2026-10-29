"""Aplicação HTTP da API de Account (decisões 0014, 0098 e 0100).

Veja `docs/loop/RESOURCE-CONTROL-LOOP.md` §6.

A API autentica, autoriza, valida e **admite a escrita de forma síncrona**: numa transação do SSOT
grava a Account e o `desired` no outbox (o Publisher publica depois). Não há Operation: `PATCH`
responde `200` e `DELETE` responde `202`, com o `Resource`; a convergência se acompanha lendo o
recurso (`observedGeneration`, `phase` e `conditions`). O auto-cadastro é a única escrita anônima:
responde `202` com o `resourceId`, igual exista ou não o e-mail. Ela não tem credencial no
provedor de identidade. As leituras vêm das views do SSOT.

Cada Account é de si mesma: o dono lê e altera só a própria conta; o operador, qualquer uma. A
exclusão segura (decisão 0040) consulta as projeções locais do `DESIRED` dos outros módulos, sem
chamada HTTP (decisão 0100).
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

from core_account.api.domain import principal as permissions
from core_account.api.domain.account import deletion_protected, normalize_email
from core_account.api.domain.admission import Admission
from core_account.api.domain.attachments import describe_all
from core_account.api.domain.errors import (
    ApiError,
    bad_request,
    conflict,
    forbidden,
    not_found,
    unauthorized,
)
from core_account.api.domain.principal import Principal
from core_account.api.domain.ratelimit import SlidingWindowLimiter
from core_account.api.domain.records import ResourceRecord
from core_account.api.domain.requests import checked_idempotency_key, request_digest
from core_account.api.domain.views import account_view
from core_account.api.http.admission import admit, register
from core_account.api.http.health_routes import register_health_routes
from core_account.api.http.ports import AdmissionStore, Attachments, Repository
from core_account.api.http.trace_context import TraceContextMiddleware
from core_account.api.settings import AccountApiSettings
from core_account.common.contracts import generated
from core_account.common.ids import new_identifier, utc_now
from core_account.common.logging_config import bind_context

logger = logging.getLogger(__name__)

ANONYMOUS = "anonymous"


class Authenticator(Protocol):
    async def verify(self, token: str) -> Principal: ...


@dataclass(frozen=True)
class Dependencies:
    settings: AccountApiSettings
    authenticator: Authenticator
    repository: Repository
    admissions: AdmissionStore
    attachments: Attachments
    limiter: SlidingWindowLimiter
    are_attachments_synced: Callable[[], bool] = lambda: True
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
    app = FastAPI(title="smarkee core account api", docs_url=None, redoc_url=None, openapi_url=None)
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

    async def own_account(principal: Principal, account_id: str) -> ResourceRecord:
        record = await deps.repository.get_account(account_id)
        if record is None or not (principal.is_operator or principal.subject == record.resource_id):
            raise not_found()
        return record

    def require_nothing_attached(principal: Principal, account_id: str) -> None:
        """Exclusão segura (decisão 0040): a conta só sai se nenhum recurso depender dela.

        As projeções locais só respondem pelo que o solicitante pode conferir: a própria conta.
        Projeção ainda sincronizando é indisponibilidade temporária, nunca "nada atrelado".
        """
        if principal.subject != account_id:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "ResourcesNotVerifiable",
                "Ainda não é possível verificar os recursos atrelados a outra conta.",
            )
        if not deps.are_attachments_synced():
            raise ApiError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "ProjectionSyncPending",
                "Não foi possível verificar os recursos da conta agora. Tente novamente.",
                headers={"Retry-After": "2"},
            )
        attached = deps.attachments.of(account_id)
        if attached:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "ResourcesAttached",
                f"A conta tem recursos atrelados: {describe_all(attached)}. Remova-os e repita.",
            )

    def check_version(record: ResourceRecord, version: str) -> None:
        if str(record.resource_version) != version:
            raise conflict()

    def client_origin(request: Request) -> str:
        header = deps.settings.api.client_address_header
        forwarded = request.headers.get(header, "") if header else ""
        if forwarded:
            # O último valor foi acrescentado pelo gateway; os anteriores vêm do cliente.
            return forwarded.split(",")[-1].strip()
        return request.client.host if request.client else "unknown"

    def admission_for(
        requested_by: str,
        operation: Literal["create", "update", "delete"],
        resource_id: str,
        idempotency_key: str | None,
        content: Mapping[str, Any],
        **extra: Any,
    ) -> Admission:
        return Admission(
            operation=operation,
            resource_id=resource_id,
            requested_by=requested_by,
            correlation_id=deps.identifiers(),
            request_digest=request_digest(content),
            now=deps.clock(),
            message_id=deps.identifiers(),
            idempotency_key=checked_idempotency_key(idempotency_key),
            **extra,
        )

    # ------------------------------------------------------------ accounts

    @app.post(
        "/v1/core/accounts",
        status_code=202,
        response_model=generated.AccountRegistrationResponse,
        response_model_exclude_none=True,
    )
    async def register_account(
        request: Request, body: generated.AccountCreateRequest
    ) -> generated.AccountRegistrationResponse:
        """Auto-cadastro: escrita anônima (`RESOURCE-CONTROL-LOOP.md` §6.1.2).

        Resposta uniforme: o mesmo `202` com um `resourceId` novo exista ou não o e-mail. Se ele já
        está em uso, nada é gravado.
        """
        bind_context(requested_by=ANONYMOUS)
        origin = client_origin(request)
        if not deps.limiter.allow(origin):
            raise ApiError(
                HTTPStatus.TOO_MANY_REQUESTS,
                "RateLimited",
                "Muitas tentativas. Tente novamente mais tarde.",
                headers={"Retry-After": str(deps.limiter.retry_after_seconds(origin))},
            )
        specification: dict[str, Any] = {
            "givenName": body.given_name,
            "familyName": body.family_name,
            "email": normalize_email(str(body.email)),
            "platformAccess": "granted",
            "platformPermissions": sorted(set(deps.settings.platform.permissions)),
        }
        resource_id = deps.identifiers()
        await register(
            deps.admissions,
            admission_for(
                ANONYMOUS,
                "create",
                resource_id,
                None,
                {"operation": "create", "specification": specification},
                specification=specification,
            ),
        )
        return generated.AccountRegistrationResponse.model_validate({"resourceId": resource_id})

    @app.get(
        "/v1/core/accounts/{account_id}",
        response_model=generated.Account,
        response_model_exclude_none=True,
    )
    async def get_account(account_id: str, principal: Authenticated) -> generated.Account:
        require(principal, permissions.ACCOUNT_GET)
        return account_view(await own_account(principal, account_id))

    @app.patch(
        "/v1/core/accounts/{account_id}",
        status_code=200,
        response_model=generated.Account,
        response_model_exclude_none=True,
    )
    async def update_account(
        account_id: str,
        body: generated.AccountUpdateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.Account:
        """Única alteração possível: a proteção contra exclusão (decisão 0043).

        Usa a mesma permissão do `delete`: quem pode apagar a conta pode (des)proteger.
        """
        require(principal, permissions.ACCOUNT_DELETE)
        record = await own_account(principal, account_id)
        if not body.resource_version.isdigit():
            raise bad_request("resourceVersion deve ser numérico.", field="resourceVersion")
        check_version(record, body.resource_version)
        specification = {"deletionProtection": body.deletion_protection}
        admission = admission_for(
            principal.subject,
            "update",
            account_id,
            idempotency_key,
            {
                "operation": "update",
                "resourceId": account_id,
                "resourceVersion": body.resource_version,
                "specification": specification,
            },
            resource_version=int(body.resource_version),
            specification=specification,
        )
        return account_view(await admit(deps.admissions, admission))

    @app.delete(
        "/v1/core/accounts/{account_id}",
        status_code=202,
        response_model=generated.Account,
        response_model_exclude_none=True,
    )
    async def delete_account(
        account_id: str,
        principal: Authenticated,
        resource_version: VersionQuery,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.Account:
        require(principal, permissions.ACCOUNT_DELETE)
        record = await own_account(principal, account_id)
        check_version(record, resource_version)
        if record.lifecycle == "present":
            if deletion_protected(record.desired):
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "DeletionProtected",
                    "A conta está protegida contra exclusão. Desproteja-a antes de excluir.",
                )
            require_nothing_attached(principal, account_id)
        admission = admission_for(
            principal.subject,
            "delete",
            account_id,
            idempotency_key,
            {"operation": "delete", "resourceId": account_id, "resourceVersion": resource_version},
            resource_version=int(resource_version),
        )
        return account_view(await admit(deps.admissions, admission))
