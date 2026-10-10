"""Aplicação HTTP da API (`docs/RESOURCE-CONTROL-LOOP.md` §6.1).

A API autentica, autoriza, valida, gera as identidades e **publica `requested`**; ela não
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

from core.api import principal as roles
from core.api.errors import ApiError, bad_request, forbidden, not_found, unauthorized
from core.api.principal import Principal
from core.api.publisher import Publisher, PublishError
from core.api.ratelimit import SlidingWindowLimiter
from core.api.repository import Repository, ResourceRecord
from core.api.requests import operation_id_for, request_digest
from core.api.views import MODULE, operation_view, organization_view, user_view
from core.contracts import generated
from core.ids import new_identifier, utc_now
from core.settings import ApiSettings

logger = logging.getLogger(__name__)

ANONYMOUS = "anonymous"
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
    publisher: Publisher
    limiter: SlidingWindowLimiter
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
    app = FastAPI(title="smarkee core", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.dependencies = deps
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
        logger.error("unexpected error", extra={"error_type": type(error).__name__})
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
        resource_type: str,
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
            resource_type=resource_type,
            requested_by=requested_by,
            idempotency_key=idempotency_key,
        )
        digest = request_digest(digest_content)
        if idempotency_key is not None:
            existing = await deps.repository.find_operation(
                operation_id, resource_type=resource_type
            )
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
                "emitter": "api",
                "module": MODULE,
                "resourceType": resource_type,
                "resourceId": resource_id,
                "operation": operation,
                "requestedBy": requested_by,
                "correlationId": deps.identifiers(),
                "occurredAt": now.isoformat(),
                "publishedAt": now.isoformat(),
                "data": {"operationId": operation_id, "requestDigest": digest, **extra_data},
            }
        )
        subject = f"api.requested.{MODULE}.{resource_type}.{resource_id}.{operation}"
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
        return generated.ApiAcceptedResponse.model_validate(
            {"resourceId": resource_id, "operationId": operation_id}
        )

    def is_owner(principal: Principal, record: ResourceRecord) -> bool:
        return principal.is_operator or record.desired.get("ownerUserId") == principal.subject

    async def owned_organization(principal: Principal, organization_id: str) -> ResourceRecord:
        record = await deps.repository.get_resource("organization", organization_id)
        if record is None or not is_owner(principal, record):
            raise not_found()  # não revela a existência de Organizations de outros donos
        return record

    async def own_user(principal: Principal, user_id: str) -> ResourceRecord:
        record = await deps.repository.get_resource("user", user_id)
        if record is None or not (principal.is_operator or principal.subject == record.resource_id):
            raise not_found()
        return record

    def check_version(record: ResourceRecord, version: str) -> None:
        if str(record.resource_version) != version:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Conflict",
                "O recurso mudou desde a leitura. Leia de novo e repita o pedido.",
            )

    # ------------------------------------------------------------ organizations

    @app.post(
        "/v1/organizations",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def create_organization(
        body: generated.OrganizationCreateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ApiAcceptedResponse:
        require(principal, roles.ORGANIZATION_CREATE)
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
        specification = {"name": body.name, "platformAccess": "granted"}
        return await submit(
            resource_type="organization",
            resource_id=deps.identifiers(),
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
        "/v1/organizations/{organization_id}",
        response_model=generated.Organization,
        response_model_exclude_none=True,
    )
    async def get_organization(
        organization_id: str, principal: Authenticated
    ) -> generated.Organization:
        require(principal, roles.ORGANIZATION_GET)
        return organization_view(await owned_organization(principal, organization_id))

    @app.get(
        "/v1/organizations",
        response_model=generated.OrganizationList,
        response_model_exclude_none=True,
    )
    async def list_organizations(
        principal: Authenticated,
        limit: Annotated[int, Query(ge=1, le=MAXIMUM_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        cursor: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9_-]{1,512}$")] = None,
    ) -> generated.OrganizationList:
        require(principal, roles.ORGANIZATION_LIST)
        owner = None if principal.is_operator else principal.subject
        records = await deps.repository.list_organizations(
            owner=owner, after=cursor, limit=limit + 1
        )
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
        "/v1/organizations/{organization_id}",
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
        require(principal, roles.ORGANIZATION_UPDATE)
        record = await owned_organization(principal, organization_id)
        if not body.resource_version.isdigit():
            raise bad_request("resourceVersion deve ser numérico.", field="resourceVersion")
        specification: dict[str, Any] = {}
        if body.name is not None:
            specification["name"] = body.name
        if body.platform_access is not None:
            specification["platformAccess"] = body.platform_access.value
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
            resource_type="organization",
            resource_id=organization_id,
            operation="update",
            requested_by=principal.subject,
            digest_content=content,
            extra_data=data,
            idempotency_key=idempotency_key,
        )

    @app.delete(
        "/v1/organizations/{organization_id}",
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
        require(principal, roles.ORGANIZATION_DELETE)
        record = await owned_organization(principal, organization_id)
        check_version(record, resource_version)
        return await submit(
            resource_type="organization",
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

    # ------------------------------------------------------------ users

    def client_origin(request: Request) -> str:
        header = deps.settings.client_address_header
        forwarded = request.headers.get(header, "") if header else ""
        if forwarded:
            # O último valor foi acrescentado pelo gateway; os anteriores vêm do cliente.
            return forwarded.split(",")[-1].strip()
        return request.client.host if request.client else "unknown"

    @app.post(
        "/v1/users",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def register_user(
        request: Request, body: generated.UserCreateRequest
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
            resource_type="user",
            resource_id=deps.identifiers(),
            operation="create",
            requested_by=ANONYMOUS,
            digest_content={"operation": "create", "specification": specification},
            extra_data={"specification": specification},
            idempotency_key=None,
        )

    @app.get("/v1/users/{user_id}", response_model=generated.User, response_model_exclude_none=True)
    async def get_user(user_id: str, principal: Authenticated) -> generated.User:
        require(principal, roles.USER_GET)
        return user_view(await own_user(principal, user_id))

    @app.delete(
        "/v1/users/{user_id}",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def delete_user(
        user_id: str,
        principal: Authenticated,
        resource_version: VersionQuery,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ApiAcceptedResponse:
        require(principal, roles.USER_DELETE)
        record = await own_user(principal, user_id)
        check_version(record, resource_version)
        return await submit(
            resource_type="user",
            resource_id=user_id,
            operation="delete",
            requested_by=principal.subject,
            digest_content={
                "operation": "delete",
                "resourceId": user_id,
                "resourceVersion": resource_version,
            },
            extra_data={"resourceVersion": resource_version},
            idempotency_key=idempotency_key,
        )

    # ------------------------------------------------------------ operations e saúde

    @app.get(
        "/v1/operations/{operation_id}",
        response_model=generated.Operation,
        response_model_exclude_none=True,
    )
    async def get_operation(operation_id: str, principal: Authenticated) -> generated.Operation:
        record = await deps.repository.find_operation(operation_id)
        # Só o solicitante e os operadores leem a Operation.
        # A de solicitante anônimo só é legível por operadores.
        if record is None or not (
            principal.is_operator or record.requested_by == principal.subject
        ):
            raise not_found()
        return operation_view(record)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}
