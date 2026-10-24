"""Aplicação HTTP do Receiver (`docs/RESOURCE-CONTROL-LOOP.md` §6.1).

O Receiver autentica, autoriza, valida, gera as identidades e **publica `requested`**; ele não
escreve no SSOT e não tem credencial de escrita no provedor de identidade. As leituras vêm das
views do SSOT. Toda escrita responde `202 Accepted` com o `operationId`.
"""

import logging
from http import HTTPStatus
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from core_account.common.contracts import generated
from core_account.common.logging_config import bind_context
from core_account.receiver.domain import principal as permissions
from core_account.receiver.domain.attachments import AttachmentCheckError, describe_all
from core_account.receiver.domain.errors import (
    ApiError,
    bad_request,
    forbidden,
    not_found,
    unauthorized,
)
from core_account.receiver.domain.principal import Principal
from core_account.receiver.domain.records import ResourceRecord
from core_account.receiver.domain.views import account_view, operation_view
from core_account.receiver.http.dependencies import Authenticator, Dependencies
from core_account.receiver.http.health_routes import register_health_routes
from core_account.receiver.http.submission import submit
from core_account.receiver.http.trace_context import TraceContextMiddleware

logger = logging.getLogger(__name__)

ANONYMOUS = "anonymous"

__all__ = ["Authenticator", "Dependencies", "create_app"]


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

    async def require_nothing_attached(principal: Principal, account_id: str) -> None:
        """Exclusão segura (decisão 0040): a conta só sai se nenhum recurso depender dela.

        Cada módulo só responde pelo que pertence a quem chama, então só dá para conferir a
        própria conta. Na dúvida (módulo indisponível ou sem permissão), a exclusão não segue.
        """
        if principal.subject != account_id:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "ResourcesNotVerifiable",
                "Ainda não é possível verificar os recursos atrelados a outra conta.",
            )
        try:
            attached = await deps.resources.of(principal.access_token)
        except AttachmentCheckError as error:
            if error.retryable:
                raise ApiError(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "ServiceUnavailable",
                    "Não foi possível verificar os recursos da conta agora. Tente novamente.",
                    headers={"Retry-After": "5"},
                ) from None
            raise ApiError(
                HTTPStatus.CONFLICT,
                "ResourcesNotVerifiable",
                "Não foi possível verificar os recursos da conta: um módulo recusou a consulta. "
                "Renove a sessão e tente de novo.",
            ) from None
        if attached:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "ResourcesAttached",
                f"A conta tem recursos atrelados: {describe_all(attached)}. Remova-os e repita.",
            )

    def check_version(record: ResourceRecord, version: str) -> None:
        if str(record.resource_version) != version:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Conflict",
                "O recurso mudou desde a leitura. Leia de novo e repita o pedido.",
            )

    # ------------------------------------------------------------ accounts

    def client_origin(request: Request) -> str:
        header = deps.settings.client_address_header
        forwarded = request.headers.get(header, "") if header else ""
        if forwarded:
            # O último valor foi acrescentado pelo gateway; os anteriores vêm do cliente.
            return forwarded.split(",")[-1].strip()
        return request.client.host if request.client else "unknown"

    @app.post(
        "/v1/core/accounts",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def register_account(
        request: Request, body: generated.AccountCreateRequest
    ) -> JSONResponse | generated.ApiAcceptedResponse:
        """Auto-cadastro: escrita anônima (`RESOURCE-CONTROL-LOOP.md` §6.1.2).

        Resposta uniforme: nenhuma consulta ao SSOT, e o mesmo `202` exista ou não o e-mail.
        """
        origin = client_origin(request)
        if not deps.limiter.allow(origin):
            raise ApiError(
                HTTPStatus.TOO_MANY_REQUESTS,
                "RateLimited",
                "Muitas tentativas. Tente novamente mais tarde.",
                headers={"Retry-After": str(deps.limiter.retry_after_seconds(origin))},
            )
        specification = {
            "givenName": body.given_name,
            "familyName": body.family_name,
            "email": str(body.email),
        }
        return await submit(
            deps,
            resource_id=deps.identifiers(),
            operation="create",
            requested_by=ANONYMOUS,
            digest_content={"operation": "create", "specification": specification},
            extra_data={"specification": specification},
            idempotency_key=None,
        )

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
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def update_account(
        account_id: str,
        body: generated.AccountUpdateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ApiAcceptedResponse:
        """Única alteração possível: a proteção contra exclusão (decisão 0043).

        Usa a mesma permissão do `delete`: quem pode apagar a conta pode (des)proteger.
        """
        require(principal, permissions.ACCOUNT_DELETE)
        record = await own_account(principal, account_id)
        check_version(record, body.resource_version)
        specification = {"deletionProtection": body.deletion_protection}
        return await submit(
            deps,
            resource_id=account_id,
            operation="update",
            requested_by=principal.subject,
            digest_content={
                "operation": "update",
                "resourceId": account_id,
                "resourceVersion": body.resource_version,
                "specification": specification,
            },
            extra_data={"resourceVersion": body.resource_version, "specification": specification},
            idempotency_key=idempotency_key,
        )

    @app.delete(
        "/v1/core/accounts/{account_id}",
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
        require(principal, permissions.ACCOUNT_DELETE)
        record = await own_account(principal, account_id)
        check_version(record, resource_version)
        if record.desired.get("deletionProtection", True) is not False:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "DeletionProtected",
                "A conta está protegida contra exclusão. Desproteja-a antes de excluir.",
            )
        await require_nothing_attached(principal, account_id)
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
        "/v1/core/accounts/{account_id}/operations/{operation_id}",
        response_model=generated.Operation,
        response_model_exclude_none=True,
    )
    async def get_operation(
        account_id: str, operation_id: str, principal: Authenticated
    ) -> generated.Operation:
        record = await deps.repository.find_operation(operation_id)
        # Só o solicitante e os operadores leem a Operation, e ela deve ser do recurso da rota.
        # A de solicitante anônimo (o cadastro) só é legível por operadores.
        if (
            record is None
            or record.resource_id != account_id
            or not (principal.is_operator or record.requested_by == principal.subject)
        ):
            raise not_found()
        return operation_view(record)
