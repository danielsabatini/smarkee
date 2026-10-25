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

from ipm_permission.common.contracts import generated
from ipm_permission.common.ids import new_identifier, utc_now
from ipm_permission.common.logging_config import bind_context
from ipm_permission.common.ports import Publisher
from ipm_permission.receiver.domain import principal as permissions
from ipm_permission.receiver.domain.errors import (
    ApiError,
    bad_request,
    forbidden,
    not_found,
    unauthorized,
)
from ipm_permission.receiver.domain.principal import Principal
from ipm_permission.receiver.domain.records import ResourceRecord
from ipm_permission.receiver.domain.views import operation_view, permission_view
from ipm_permission.receiver.http.health_routes import register_health_routes
from ipm_permission.receiver.http.ports import Repository
from ipm_permission.receiver.http.submission import submit
from ipm_permission.receiver.http.trace_context import TraceContextMiddleware

logger = logging.getLogger(__name__)


class Authenticator(Protocol):
    async def verify(self, token: str) -> Principal: ...


@dataclass(slots=True)
class Dependencies:
    repository: Repository
    publisher: Publisher
    authenticator: Authenticator
    is_ready: Callable[[], bool] = lambda: True
    clock: Callable[[], datetime] = utc_now
    identifiers: Callable[[], str] = new_identifier


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
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Conflict",
                "O recurso mudou desde a leitura. Leia de novo e repita o pedido.",
            )

    @app.post(
        "/v1/ipm/permissions",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def create_permission(
        body: generated.PermissionCreateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ApiAcceptedResponse:
        require(principal, permissions.PERMISSION_ADMIN)
        if body.description.strip() == body.name.strip():
            raise bad_request(
                "A descrição da permissão deve descrever a ação e não repetir a chave.",
                field="description",
            )
        specification: dict[str, Any] = {
            "name": body.name,
            "description": body.description,
            "grantable": body.grantable,
        }
        new_permission_id = deps.identifiers()
        return await submit(
            deps,
            resource_id=new_permission_id,
            operation="create",
            requested_by=principal.subject,
            digest_content={"operation": "create", "specification": specification},
            extra_data={"specification": specification},
            idempotency_key=idempotency_key,
        )

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
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        after: Annotated[str | None, Query(max_length=128)] = None,
    ) -> generated.PermissionList:
        require(principal, permissions.PERMISSION_LIST)
        records = await deps.repository.list_permissions(after=after, limit=limit + 1)
        has_more = len(records) > limit
        page = records[:limit]
        return generated.PermissionList.model_validate(
            {
                "items": [permission_view(item) for item in page],
                "nextCursor": page[-1].resource_id if has_more else None,
            }
        )

    @app.patch(
        "/v1/ipm/permissions/{permission_id}",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def update_permission(
        permission_id: str,
        body: generated.PermissionUpdateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ApiAcceptedResponse:
        require(principal, permissions.PERMISSION_ADMIN)
        record = await existing_permission(permission_id)
        if record.lifecycle != "present":
            raise bad_request("Não é possível alterar uma Permission em remoção.")
        check_version(record, body.resource_version)

        changes = body.model_dump(by_alias=True, exclude_unset=True)
        specification: dict[str, Any] = {}
        if "description" in changes and body.description is not None:
            if body.description.strip() == str(record.desired.get("name", "")).strip():
                raise bad_request(
                    "A descrição da permissão deve descrever a ação e não repetir a chave.",
                    field="description",
                )
            specification["description"] = body.description
        if "grantable" in changes and body.grantable is not None:
            specification["grantable"] = body.grantable
        if "deletionProtection" in changes and body.deletion_protection is not None:
            specification["deletionProtection"] = body.deletion_protection
        extra: dict[str, Any] = {"resourceVersion": body.resource_version}
        if specification:
            extra["specification"] = specification
        if body.reconciliation is not None:
            extra["reconciliation"] = body.reconciliation.value
        return await submit(
            deps,
            resource_id=permission_id,
            operation="update",
            requested_by=principal.subject,
            digest_content={"operation": "update", "resourceId": permission_id, **extra},
            extra_data=extra,
            idempotency_key=idempotency_key,
        )

    @app.delete(
        "/v1/ipm/permissions/{permission_id}",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def delete_permission(
        permission_id: str,
        version: VersionQuery,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ApiAcceptedResponse:
        require(principal, permissions.PERMISSION_ADMIN)
        record = await existing_permission(permission_id)
        check_version(record, version)
        if record.desired.get("deletionProtection", True) is not False:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "DeletionProtected",
                "A Permission está protegida contra exclusão."
                " Desative deletionProtection antes de remover.",
            )
        extra = {"resourceVersion": version}
        return await submit(
            deps,
            resource_id=permission_id,
            operation="delete",
            requested_by=principal.subject,
            digest_content={"operation": "delete", "resourceId": permission_id, **extra},
            extra_data=extra,
            idempotency_key=idempotency_key,
        )

    # ------------------------------------------------------------ operations e saúde

    @app.get(
        "/v1/ipm/permissions/{permission_id}/operations/{operation_id}",
        response_model=generated.Operation,
        response_model_exclude_none=True,
    )
    async def get_operation(
        permission_id: str, operation_id: str, principal: Authenticated
    ) -> generated.Operation:
        record = await deps.repository.find_operation(operation_id)
        if (
            record is None
            or record.resource_id != permission_id
            or not (principal.is_operator or record.requested_by == principal.subject)
        ):
            raise not_found()
        return operation_view(record)
