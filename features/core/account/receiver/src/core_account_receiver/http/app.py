"""Aplicação HTTP do Receiver (`docs/RESOURCE-CONTROL-LOOP.md` §6.1).

O Receiver autentica, autoriza, valida, gera as identidades e **publica `requested`**; ele não
escreve no SSOT e não tem credencial de escrita no provedor de identidade. As leituras vêm das
views do SSOT. Toda escrita responde `202 Accepted` com o `operationId`.
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

from core_account_receiver.contracts import generated
from core_account_receiver.domain import principal as roles
from core_account_receiver.domain.attachments import AttachmentCheckError, describe_all
from core_account_receiver.domain.errors import (
    ApiError,
    bad_request,
    forbidden,
    not_found,
    unauthorized,
)
from core_account_receiver.domain.principal import Principal
from core_account_receiver.domain.ratelimit import SlidingWindowLimiter
from core_account_receiver.domain.records import ResourceRecord
from core_account_receiver.domain.requests import operation_id_for, request_digest
from core_account_receiver.domain.views import MODULE, account_view, operation_view
from core_account_receiver.http.ports import (
    AttachedResources,
    Publisher,
    PublishError,
    Repository,
)
from core_account_receiver.http.trace_context import TraceContextMiddleware
from core_account_receiver.ids import new_identifier, utc_now
from core_account_receiver.settings import ApiSettings

logger = logging.getLogger(__name__)

ANONYMOUS = "anonymous"
RESOURCE_TYPE = "account"


class Authenticator(Protocol):
    async def verify(self, token: str) -> Principal: ...


@dataclass(frozen=True)
class Dependencies:
    settings: ApiSettings
    authenticator: Authenticator
    repository: Repository
    publisher: Publisher
    limiter: SlidingWindowLimiter
    resources: AttachedResources
    is_ready: Callable[[], bool] = lambda: True
    """Prontidão das dependências críticas (NATS); usada por `/health/ready`."""
    clock: Callable[[], datetime] = utc_now
    identifiers: Callable[[], str] = new_identifier


async def authenticate(request: Request) -> Principal:
    deps: Dependencies = request.app.state.dependencies
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthorized()
    return await deps.authenticator.verify(token.strip())


Authenticated = Annotated[Principal, Depends(authenticate)]
IdempotencyKey = Annotated[str | None, Header()]
VersionQuery = Annotated[str, Query(alias="resourceVersion", pattern=r"^[0-9]{1,18}$")]


def create_app(deps: Dependencies) -> FastAPI:
    app = FastAPI(title="smarkee core account api", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.dependencies = deps
    app.add_middleware(TraceContextMiddleware)
    _register_error_handlers(app)
    _register_routes(app, deps)
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
    def require(principal: Principal, role: str) -> None:
        if not principal.has_role(role):
            raise forbidden()

    async def submit(
        *,
        resource_id: str,
        operation: str,
        requested_by: str,
        digest_content: dict[str, Any],
        extra_data: dict[str, Any],
        idempotency_key: str | None,
    ) -> generated.ApiAcceptedResponse:
        """Gera a identidade da Operation, evita republicar e publica o `requested`."""
        operation_id = operation_id_for(
            module=MODULE,
            resource_type=RESOURCE_TYPE,
            requested_by=requested_by,
            idempotency_key=idempotency_key,
        )
        digest = request_digest(digest_content)
        if idempotency_key is not None:
            existing = await deps.repository.find_operation(operation_id)
            if existing is not None:
                if existing.request_digest != digest:
                    raise ApiError(
                        HTTPStatus.UNPROCESSABLE_ENTITY,
                        "IdempotencyKeyReused",
                        "A Idempotency-Key já foi usada com outro conteúdo.",
                    )
                return generated.ApiAcceptedResponse.model_validate(
                    {"resourceId": existing.resource_id, "operationId": existing.operation_id}
                )
        now = deps.clock()
        message_id = deps.identifiers()
        envelope = generated.MessageEnvelope.model_validate(
            {
                "messageId": message_id,
                "schemaVersion": "1.0",
                "messageType": "requested",
                "emitter": "receiver",
                "module": MODULE,
                "resourceType": RESOURCE_TYPE,
                "resourceId": resource_id,
                "operation": operation,
                "requestedBy": requested_by,
                "correlationId": deps.identifiers(),
                "occurredAt": now.isoformat(),
                "publishedAt": now.isoformat(),
                "data": {"operationId": operation_id, "requestDigest": digest, **extra_data},
            }
        )
        subject = f"receiver.requested.{MODULE}.{RESOURCE_TYPE}.{resource_id}.{operation}"
        try:
            await deps.publisher.publish(
                subject, envelope.model_dump_json(exclude_none=True).encode(), message_id=message_id
            )
        except PublishError:
            raise ApiError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "ServiceUnavailable",
                "Não foi possível registrar o pedido agora. Tente novamente.",
                headers={"Retry-After": "5"},
            ) from None
        logger.info(
            "request published",
            extra={
                "smarkee.resource.id": resource_id,
                "smarkee.operation.name": operation,
                "smarkee.outcome": "accepted",
            },
        )
        return generated.ApiAcceptedResponse.model_validate(
            {"resourceId": resource_id, "operationId": operation_id}
        )

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
        require(principal, roles.ACCOUNT_GET)
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

        Usa a mesma role do `delete`: quem pode apagar a conta pode (des)proteger.
        """
        require(principal, roles.ACCOUNT_DELETE)
        record = await own_account(principal, account_id)
        check_version(record, body.resource_version)
        specification = {"deletionProtection": body.deletion_protection}
        return await submit(
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
        require(principal, roles.ACCOUNT_DELETE)
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

    # Probes (decisão 0018): só pela rede interna; o gateway publica apenas `/v1/...`. A liveness
    # não consulta dependências; a readiness inclui o NATS.
    @app.get("/health/live")
    async def health_live() -> dict[str, str]:
        return {"status": "UP"}

    @app.get("/health/startup")
    async def health_startup() -> dict[str, str]:
        return {"status": "UP"}

    @app.get("/health/ready")
    async def health_ready() -> JSONResponse:
        ready = deps.is_ready()
        return JSONResponse(
            {"status": "UP" if ready else "DOWN", "checks": {"nats": "UP" if ready else "DOWN"}},
            status_code=HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
        )
