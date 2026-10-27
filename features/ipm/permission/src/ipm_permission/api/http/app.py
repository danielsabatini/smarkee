"""Aplicação HTTP da API (decisão 0098; `docs/loop/RESOURCE-CONTROL-LOOP.md` §6).

A API autentica, autoriza, valida e **admite a escrita de forma síncrona**: numa transação do SSOT
grava o recurso e o `desired` no outbox (o Publisher publica depois). Não há Operation: `POST`
responde `201`, `PATCH` responde `200` e `DELETE` responde `202`, todos com o `Resource`; a
convergência se acompanha lendo o recurso (`observedGeneration`, `phase` e `conditions`). Ela não
tem credencial no provedor de identidade. As leituras vêm das views do SSOT.

Permissions são do catálogo da plataforma: só o operador (`ipm.permission.admin`) as cria, altera
e remove; quem tem `get` ou `list` lê (decisão 0083).
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

from ipm_permission.api.domain import principal as permissions
from ipm_permission.api.domain.admission import Admission
from ipm_permission.api.domain.errors import (
    ApiError,
    bad_request,
    conflict,
    forbidden,
    not_found,
    unauthorized,
)
from ipm_permission.api.domain.permission import deletion_protected, description_repeats_name
from ipm_permission.api.domain.principal import Principal
from ipm_permission.api.domain.records import ResourceRecord
from ipm_permission.api.domain.requests import checked_idempotency_key, request_digest
from ipm_permission.api.domain.views import permission_view
from ipm_permission.api.http.admission import admit
from ipm_permission.api.http.health_routes import register_health_routes
from ipm_permission.api.http.ports import AdmissionStore, Repository
from ipm_permission.api.http.trace_context import TraceContextMiddleware
from ipm_permission.common.contracts import generated
from ipm_permission.common.ids import new_identifier, utc_now
from ipm_permission.common.logging_config import bind_context

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 50
MAXIMUM_PAGE_SIZE = 200


class Authenticator(Protocol):
    async def verify(self, token: str) -> Principal: ...


@dataclass(frozen=True)
class Dependencies:
    authenticator: Authenticator
    repository: Repository
    admissions: AdmissionStore
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
        title="smarkee ipm permission api", docs_url=None, redoc_url=None, openapi_url=None
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

    async def existing_permission(permission_id: str) -> ResourceRecord:
        record = await deps.repository.get_permission(permission_id)
        if record is None:
            raise not_found()
        return record

    def check_version(record: ResourceRecord, version: str) -> None:
        if str(record.resource_version) != version:
            raise conflict()

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

    @app.post(
        "/v1/ipm/permissions",
        status_code=201,
        response_model=generated.Permission,
        response_model_exclude_none=True,
    )
    async def create_permission(
        body: generated.PermissionCreateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.Permission:
        require(principal, permissions.PERMISSION_ADMIN)
        if description_repeats_name(body.description, body.name):
            raise bad_request(
                "A descrição da permissão deve descrever a ação e não repetir a chave.",
                field="description",
            )
        specification: dict[str, Any] = {
            "name": body.name.strip(),
            "description": body.description.strip(),
            "grantable": body.grantable,
        }
        admission = admission_for(
            principal,
            "create",
            deps.identifiers(),
            idempotency_key,
            {"operation": "create", "specification": specification},
            specification=specification,
        )
        return permission_view(await admit(deps.admissions, admission))

    @app.get(
        "/v1/ipm/permissions/{permission_id}",
        response_model=generated.Permission,
        response_model_exclude_none=True,
    )
    async def get_permission(permission_id: str, principal: Authenticated) -> generated.Permission:
        require(principal, permissions.PERMISSION_GET)
        return permission_view(await existing_permission(permission_id))

    @app.get(
        "/v1/ipm/permissions",
        response_model=generated.PermissionList,
        response_model_exclude_none=True,
    )
    async def list_permissions(
        principal: Authenticated,
        limit: Annotated[int, Query(ge=1, le=MAXIMUM_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        after: Annotated[str | None, Query(max_length=128)] = None,
    ) -> generated.PermissionList:
        require(principal, permissions.PERMISSION_LIST)
        records = await deps.repository.list_permissions(after=after, limit=limit + 1)
        page = records[:limit]
        return generated.PermissionList.model_validate(
            {
                "items": [permission_view(item) for item in page],
                "nextCursor": page[-1].resource_id if len(records) > limit else None,
            }
        )

    @app.patch(
        "/v1/ipm/permissions/{permission_id}",
        status_code=200,
        response_model=generated.Permission,
        response_model_exclude_none=True,
    )
    async def update_permission(
        permission_id: str,
        body: generated.PermissionUpdateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.Permission:
        require(principal, permissions.PERMISSION_ADMIN)
        record = await existing_permission(permission_id)
        if not body.resource_version.isdigit():
            raise bad_request("resourceVersion deve ser numérico.", field="resourceVersion")
        specification: dict[str, Any] = {}
        if body.description is not None:
            specification["description"] = body.description.strip()
        if body.grantable is not None:
            specification["grantable"] = body.grantable
        if body.deletion_protection is not None:
            specification["deletionProtection"] = body.deletion_protection
        reconciliation = body.reconciliation.value if body.reconciliation is not None else None
        if not specification and reconciliation is None:
            raise bad_request("Informe ao menos um campo a alterar.")
        check_version(record, body.resource_version)
        content: dict[str, Any] = {
            "operation": "update",
            "resourceId": permission_id,
            "resourceVersion": body.resource_version,
        }
        if specification:
            content["specification"] = specification
        if reconciliation is not None:
            content["reconciliation"] = reconciliation
        admission = admission_for(
            principal,
            "update",
            permission_id,
            idempotency_key,
            content,
            resource_version=int(body.resource_version),
            specification=specification or None,
            reconciliation=reconciliation,
        )
        return permission_view(await admit(deps.admissions, admission))

    @app.delete(
        "/v1/ipm/permissions/{permission_id}",
        status_code=202,
        response_model=generated.Permission,
        response_model_exclude_none=True,
    )
    async def delete_permission(
        permission_id: str,
        principal: Authenticated,
        resource_version: VersionQuery,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.Permission:
        require(principal, permissions.PERMISSION_ADMIN)
        record = await existing_permission(permission_id)
        check_version(record, resource_version)
        if deletion_protected(record.desired):
            raise ApiError(
                HTTPStatus.CONFLICT,
                "DeletionProtected",
                "A Permission está protegida contra exclusão."
                " Desative deletionProtection antes de remover.",
            )
        admission = admission_for(
            principal,
            "delete",
            permission_id,
            idempotency_key,
            {
                "operation": "delete",
                "resourceId": permission_id,
                "resourceVersion": resource_version,
            },
            resource_version=int(resource_version),
        )
        return permission_view(await admit(deps.admissions, admission))
