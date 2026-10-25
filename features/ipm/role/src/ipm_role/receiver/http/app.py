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

from ipm_role.common.contracts import generated
from ipm_role.common.ids import new_identifier, utc_now
from ipm_role.common.logging_config import bind_context
from ipm_role.common.ports import Publisher
from ipm_role.receiver.domain import principal as permissions
from ipm_role.receiver.domain.errors import (
    ApiError,
    bad_request,
    forbidden,
    not_found,
    unauthorized,
)
from ipm_role.receiver.domain.principal import Principal
from ipm_role.receiver.domain.records import ResourceRecord
from ipm_role.receiver.domain.views import operation_view, role_view
from ipm_role.receiver.http.health_routes import register_health_routes
from ipm_role.receiver.http.ports import Repository
from ipm_role.receiver.http.submission import submit
from ipm_role.receiver.http.trace_context import TraceContextMiddleware

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
    app = FastAPI(title="smarkee ipm role api", docs_url=None, redoc_url=None, openapi_url=None)
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

    async def existing_role(role_id: str) -> ResourceRecord:
        record = await deps.repository.get_role(role_id)
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
        "/v1/ipm/roles",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def create_role(
        body: generated.RoleCreateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ApiAcceptedResponse:
        require(principal, permissions.ROLE_ADMIN)
        specification: dict[str, Any] = {
            "name": body.name,
            "description": body.description,
            "permissions": sorted({item.root for item in body.permissions}),
        }
        new_role_id = deps.identifiers()
        return await submit(
            deps,
            resource_id=new_role_id,
            operation="create",
            requested_by=principal.subject,
            digest_content={"operation": "create", "specification": specification},
            extra_data={"specification": specification},
            idempotency_key=idempotency_key,
        )

    @app.get(
        "/v1/ipm/roles/{role_id}",
        response_model=generated.Role,
        response_model_exclude_none=True,
    )
    async def get_role(role_id: str, principal: Authenticated) -> generated.Role:
        require(principal, permissions.ROLE_GET)
        return role_view(await existing_role(role_id))

    @app.get(
        "/v1/ipm/roles",
        response_model=generated.RoleList,
        response_model_exclude_none=True,
    )
    async def list_roles(
        principal: Authenticated,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        after: Annotated[str | None, Query(max_length=128)] = None,
    ) -> generated.RoleList:
        require(principal, permissions.ROLE_LIST)
        records = await deps.repository.list_roles(after=after, limit=limit + 1)
        has_more = len(records) > limit
        page = records[:limit]
        return generated.RoleList.model_validate(
            {
                "items": [role_view(item) for item in page],
                "nextCursor": page[-1].resource_id if has_more else None,
            }
        )

    @app.patch(
        "/v1/ipm/roles/{role_id}",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def update_role(
        role_id: str,
        body: generated.RoleUpdateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ApiAcceptedResponse:
        require(principal, permissions.ROLE_ADMIN)
        record = await existing_role(role_id)
        if record.lifecycle != "present":
            raise bad_request("Não é possível alterar uma Role em remoção.")
        check_version(record, body.resource_version)

        changes = body.model_dump(by_alias=True, exclude_unset=True)
        specification: dict[str, Any] = {}
        if "description" in changes and body.description is not None:
            specification["description"] = body.description
        if "permissions" in changes and body.permissions is not None:
            specification["permissions"] = sorted({item.root for item in body.permissions})
        if "deletionProtection" in changes and body.deletion_protection is not None:
            specification["deletionProtection"] = body.deletion_protection
        extra: dict[str, Any] = {"resourceVersion": body.resource_version}
        if specification:
            extra["specification"] = specification
        if body.reconciliation is not None:
            extra["reconciliation"] = body.reconciliation.value
        return await submit(
            deps,
            resource_id=role_id,
            operation="update",
            requested_by=principal.subject,
            digest_content={"operation": "update", "resourceId": role_id, **extra},
            extra_data=extra,
            idempotency_key=idempotency_key,
        )

    @app.delete(
        "/v1/ipm/roles/{role_id}",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def delete_role(
        role_id: str,
        version: VersionQuery,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ApiAcceptedResponse:
        require(principal, permissions.ROLE_ADMIN)
        record = await existing_role(role_id)
        check_version(record, version)
        if record.desired.get("deletionProtection", True) is not False:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "DeletionProtected",
                "A Role está protegida contra exclusão."
                " Desative deletionProtection antes de remover.",
            )
        extra = {"resourceVersion": version}
        return await submit(
            deps,
            resource_id=role_id,
            operation="delete",
            requested_by=principal.subject,
            digest_content={"operation": "delete", "resourceId": role_id, **extra},
            extra_data=extra,
            idempotency_key=idempotency_key,
        )

    # ------------------------------------------------------------ operations e saúde

    @app.get(
        "/v1/ipm/roles/{role_id}/operations/{operation_id}",
        response_model=generated.Operation,
        response_model_exclude_none=True,
    )
    async def get_operation(
        role_id: str, operation_id: str, principal: Authenticated
    ) -> generated.Operation:
        record = await deps.repository.find_operation(operation_id)
        if (
            record is None
            or record.resource_id != role_id
            or not (principal.is_operator or record.requested_by == principal.subject)
        ):
            raise not_found()
        return operation_view(record)
