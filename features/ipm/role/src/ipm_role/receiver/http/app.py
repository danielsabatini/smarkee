"""Aplicação HTTP do Receiver (`docs/RESOURCE-CONTROL-LOOP.md` §6.1, decisão 0092).

O Receiver autentica, autoriza, valida, gera as identidades e **publica `requested`**; ele não
escreve no SSOT. As leituras vêm das views do SSOT. Toda escrita responde `202 Accepted` com o
`operationId`.

Escopo por Organization: o operador age em qualquer uma; o dono (root) e os usuários da
Organization, só nela. As Roles `predefined` (Organization `core`) são legíveis por todos e
alteráveis só pelo operador.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Any, Protocol

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ipm_role.common.catalog import GrantableCatalog
from ipm_role.common.contracts import generated
from ipm_role.common.ids import new_identifier, utc_now
from ipm_role.common.logging_config import bind_context
from ipm_role.common.ports import Publisher
from ipm_role.receiver.domain import principal as permissions
from ipm_role.receiver.domain.access import (
    AccessCheckError,
    OrganizationAccess,
    permissions_changed,
)
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
from ipm_role.receiver.http.ports import Organizations, Repository, RoleUsage, Users
from ipm_role.receiver.http.submission import submit
from ipm_role.receiver.http.trace_context import TraceContextMiddleware
from ipm_role.receiver.settings import ApiSettings

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 50
MAXIMUM_PAGE_SIZE = 200
RETRY_AFTER_SECONDS = "5"
RESOURCE_ID_PATTERN = r"^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$"
PLATFORM_ORGANIZATION_ID = "core"
"""Organization de sistema, dona das Roles `predefined`; reservada (decisão 0092)."""


class Authenticator(Protocol):
    async def verify(self, token: str) -> Principal: ...


class Standing(StrEnum):
    """Como o solicitante se relaciona com a Organization do pedido."""

    OPERATOR = "operator"
    OWNER = "owner"
    MEMBER = "member"


@dataclass(slots=True)
class Dependencies:
    settings: ApiSettings
    repository: Repository
    organizations: Organizations
    users: Users
    role_usage: RoleUsage
    publisher: Publisher
    authenticator: Authenticator
    grantable: GrantableCatalog = field(default_factory=GrantableCatalog)
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
OrganizationQuery = Annotated[
    str | None, Query(alias="organizationId", pattern=RESOURCE_ID_PATTERN)
]


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

    def unavailable(error: AccessCheckError) -> ApiError:
        if not error.retryable:
            return forbidden()
        return ApiError(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "OrganizationUnavailable",
            "Não foi possível confirmar o acesso agora. Tente de novo.",
            headers={"Retry-After": RETRY_AFTER_SECONDS},
        )

    async def standing_in(principal: Principal, organization_id: str) -> Standing | None:
        if principal.is_operator:
            return Standing.OPERATOR
        # Pergunta ao Receiver de User se o solicitante é membro desta Organization.
        member_of = await deps.users.get_user_organization(
            principal.subject, principal.access_token
        )
        if member_of == organization_id:
            return Standing.MEMBER
        try:
            access = await deps.organizations.access(organization_id, principal.access_token)
        except AccessCheckError as error:
            raise unavailable(error) from None
        return Standing.OWNER if access is OrganizationAccess.OWNED else None

    def organization_of(record: ResourceRecord) -> str:
        """Organization dona; dado anterior à decisão 0092 não tem o campo e vale `core`."""
        return str(record.desired.get("organizationId") or PLATFORM_ORGANIZATION_ID)

    async def visible_role(
        principal: Principal, role_id: str, *, writing: bool
    ) -> tuple[ResourceRecord, Standing | None]:
        record = await deps.repository.get_role(role_id)
        if record is None:
            raise not_found()
        organization_id = organization_of(record)
        if organization_id == PLATFORM_ORGANIZATION_ID:
            # Predefinida da plataforma: todos leem (com get/list); só o operador altera.
            if writing and not principal.is_operator:
                raise forbidden()
            return record, (Standing.OPERATOR if principal.is_operator else None)
        standing = await standing_in(principal, organization_id)
        if standing is None:
            raise not_found()  # não revela Roles de outras Organizations
        return record, standing

    def check_permissions(
        principal: Principal,
        standing: Standing,
        current: list[str],
        requested: list[str],
    ) -> None:
        """Teto de permissões (delegáveis à Organization) e `ipm.role.bind` do membro."""
        rejected = deps.grantable.outside(requested)
        if rejected:
            raise bad_request(
                f"Permissões não delegáveis à Organization: {', '.join(rejected)}.",
                field="permissions",
            )
        can_bind = standing is not Standing.MEMBER or principal.has_permission(
            permissions.ROLE_BIND
        )
        if permissions_changed(current, requested) and not can_bind:
            raise forbidden(
                f"É necessária a permissão {permissions.ROLE_BIND} para definir ou alterar"
                " as permissões de uma Role."
            )

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
        require(principal, permissions.ROLE_CREATE)
        organization_id = body.organization_id
        if organization_id == PLATFORM_ORGANIZATION_ID:
            raise bad_request(
                "A Organization `core` é reservada às Roles predefinidas.",
                field="organizationId",
            )
        standing = await standing_in(principal, organization_id)
        if standing is None:
            raise not_found()
        requested_permissions = sorted({item.root for item in body.permissions})
        check_permissions(principal, standing, [], requested_permissions)
        quota: int | None = None
        if standing is not Standing.OPERATOR:
            quota = deps.settings.role_quota
            if await deps.repository.count_custom_roles_in(organization_id) >= quota:
                raise ApiError(
                    HTTPStatus.FORBIDDEN,
                    "QuotaExceeded",
                    "Limite de Roles da Organization atingido.",
                )
        specification: dict[str, Any] = {
            "organizationId": organization_id,
            "name": body.name.strip(),
            "description": body.description.strip(),
            "permissions": requested_permissions,
        }
        new_role_id = deps.identifiers()
        return await submit(
            deps,
            log_context={"organization_id": organization_id},
            resource_id=new_role_id,
            operation="create",
            requested_by=principal.subject,
            digest_content={"operation": "create", "specification": specification},
            extra_data={
                "specification": specification,
                **({"organizationQuotaLimit": quota} if quota is not None else {}),
            },
            idempotency_key=idempotency_key,
        )

    @app.get(
        "/v1/ipm/roles/{role_id}",
        response_model=generated.Role,
        response_model_exclude_none=True,
    )
    async def get_role(role_id: str, principal: Authenticated) -> generated.Role:
        require(principal, permissions.ROLE_GET)
        record, _ = await visible_role(principal, role_id, writing=False)
        return role_view(record)

    @app.get(
        "/v1/ipm/roles",
        response_model=generated.RoleList,
        response_model_exclude_none=True,
    )
    async def list_roles(
        principal: Authenticated,
        organization_id: OrganizationQuery = None,
        limit: Annotated[int, Query(ge=1, le=MAXIMUM_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        after: Annotated[str | None, Query(max_length=128)] = None,
    ) -> generated.RoleList:
        require(principal, permissions.ROLE_LIST)
        if organization_id is not None and await standing_in(principal, organization_id) is None:
            raise not_found()
        records = await deps.repository.list_roles(
            organization_id=organization_id, after=after, limit=limit + 1
        )
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
        require(principal, permissions.ROLE_UPDATE)
        record, standing = await visible_role(principal, role_id, writing=True)
        if record.lifecycle != "present":
            raise bad_request("Não é possível alterar uma Role em remoção.")
        check_version(record, body.resource_version)

        changes = body.model_dump(by_alias=True, exclude_unset=True)
        specification: dict[str, Any] = {}
        if "description" in changes and body.description is not None:
            specification["description"] = body.description
        if "permissions" in changes and body.permissions is not None:
            requested_permissions = sorted({item.root for item in body.permissions})
            current_permissions = sorted(
                str(item) for item in record.desired.get("permissions", [])
            )
            check_permissions(
                principal, standing or Standing.OPERATOR, current_permissions, requested_permissions
            )
            specification["permissions"] = requested_permissions
        if "deletionProtection" in changes and body.deletion_protection is not None:
            specification["deletionProtection"] = body.deletion_protection
        extra: dict[str, Any] = {"resourceVersion": body.resource_version}
        if specification:
            extra["specification"] = specification
        if body.reconciliation is not None:
            if standing is not Standing.OPERATOR:
                raise forbidden()
            extra["reconciliation"] = body.reconciliation.value
        return await submit(
            deps,
            log_context={"organization_id": organization_of(record)},
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
        require(principal, permissions.ROLE_DELETE)
        record, _ = await visible_role(principal, role_id, writing=True)
        check_version(record, version)
        if record.desired.get("deletionProtection", True) is not False:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "DeletionProtected",
                "A Role está protegida contra exclusão."
                " Desative deletionProtection antes de remover.",
            )
        organization_id = organization_of(record)
        if organization_id != PLATFORM_ORGANIZATION_ID:
            # Recusa a exclusão de uma Role que usuários ou grupos da Organization ainda usam.
            try:
                in_use = await deps.role_usage.role_in_use(
                    organization_id, str(record.desired.get("name", "")), principal.access_token
                )
            except AccessCheckError as error:
                raise unavailable(error) from None
            if in_use:
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "ResourcesAttached",
                    "A Role está em uso por usuários ou grupos da Organization."
                    " Retire-a deles antes de excluir.",
                )
        extra = {"resourceVersion": version}
        return await submit(
            deps,
            log_context={"organization_id": organization_id},
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
        record, standing = await visible_role(principal, role_id, writing=False)
        operation = await deps.repository.find_operation(operation_id)
        # Operações de Roles predefinidas são só do operador (a leitura da Role é pública).
        if (
            operation is None
            or operation.resource_id != record.resource_id
            or (standing is None and organization_of(record) == PLATFORM_ORGANIZATION_ID)
        ):
            raise not_found()
        return operation_view(operation)
