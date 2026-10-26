"""Aplicação HTTP do Receiver de Grupo (`docs/loop/RESOURCE-CONTROL-LOOP.md` §6.1, decisões 0085 e
0088).

O Receiver autentica, autoriza, valida, gera as identidades e **publica `requested`**; ele não
escreve no SSOT. As leituras vêm das views do SSOT.
Toda escrita responde `202 Accepted` com o `operationId`.

Escopo por Organization: o operador age em qualquer uma; o dono (root) e os usuários
da Organization, só nela.
"""

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Any, Protocol

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ipm_group.common.catalog import RolesCatalog
from ipm_group.common.contracts import generated
from ipm_group.common.ids import new_identifier, utc_now
from ipm_group.common.logging_config import bind_context
from ipm_group.common.ports import Publisher
from ipm_group.receiver.domain import principal as permissions
from ipm_group.receiver.domain.access import (
    AccessCheckError,
    OrganizationAccess,
    binding_allowed,
    outside_roles_catalog,
)
from ipm_group.receiver.domain.errors import (
    ApiError,
    bad_request,
    forbidden,
    not_found,
    unauthorized,
)
from ipm_group.receiver.domain.principal import Principal
from ipm_group.receiver.domain.records import ResourceRecord
from ipm_group.receiver.domain.views import group_view, operation_view
from ipm_group.receiver.http.health_routes import register_health_routes
from ipm_group.receiver.http.ports import Organizations, Repository, Users
from ipm_group.receiver.http.submission import submit
from ipm_group.receiver.http.trace_context import TraceContextMiddleware
from ipm_group.receiver.settings import ApiSettings

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 50
MAXIMUM_PAGE_SIZE = 200
RETRY_AFTER_SECONDS = "5"
RESOURCE_ID_PATTERN = r"^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$"


class Authenticator(Protocol):
    async def verify(self, token: str) -> Principal: ...


class Standing(StrEnum):
    """Como o solicitante se relaciona com a Organization do pedido."""

    OPERATOR = "operator"
    OWNER = "owner"
    MEMBER = "member"


@dataclass(frozen=True)
class Dependencies:
    settings: ApiSettings
    authenticator: Authenticator
    repository: Repository
    organizations: Organizations
    users: Users
    publisher: Publisher
    catalog: RolesCatalog = field(default_factory=RolesCatalog)
    clock: Callable[[], datetime] = utc_now
    identifiers: Callable[[], str] = new_identifier
    is_ready: Callable[[], bool] = lambda: True


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
OrganizationQuery = Annotated[str, Query(alias="organizationId", pattern=RESOURCE_ID_PATTERN)]


def create_app(deps: Dependencies) -> FastAPI:
    app = FastAPI(title="smarkee ipm group api", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.dependencies = deps
    app.add_middleware(TraceContextMiddleware)
    _register_error_handlers(app)
    _register_routes(app, deps)
    register_health_routes(app, lambda: deps.is_ready())
    return app


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
        field = ".".join(str(part) for part in first["loc"][1:]) or None
        return _error_response(bad_request(f"Campo inválido: {first['msg']}", field=field))

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, error: Exception) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        logger.error("unexpected error", exc_info=error)
        return _error_response(
            ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "InternalError", "Erro interno.")
        )


def _roles_of(values: Iterable[generated.RoleName | str] | None) -> list[str]:
    return sorted({value if isinstance(value, str) else value.root for value in values or []})


def _register_routes(app: FastAPI, deps: Dependencies) -> None:
    def require(principal: Principal, permission: str) -> None:
        if not principal.has_permission(permission):
            raise forbidden()

    async def standing_in(principal: Principal, organization_id: str) -> Standing | None:
        if principal.is_operator:
            return Standing.OPERATOR
        # Pergunta ao User receiver se o subject é membro desta Organization
        member_org = await deps.users.get_user_organization(
            principal.subject, principal.access_token
        )
        if member_org == organization_id:
            return Standing.MEMBER
        try:
            access = await deps.organizations.access(organization_id, principal.access_token)
        except AccessCheckError as error:
            if not error.retryable:
                raise forbidden() from None
            raise ApiError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "OrganizationUnavailable",
                "Não foi possível confirmar a Organization agora. Tente de novo.",
                headers={"Retry-After": RETRY_AFTER_SECONDS},
            ) from None
        return Standing.OWNER if access is OrganizationAccess.OWNED else None

    async def visible_group(principal: Principal, group_id: str) -> tuple[ResourceRecord, Standing]:
        record = await deps.repository.get_group(group_id)
        if record is None:
            raise not_found()
        standing = await standing_in(principal, str(record.desired.get("organizationId", "")))
        if standing is None:
            raise not_found()
        return record, standing

    def check_roles(
        principal: Principal,
        standing: Standing,
        organization_id: str,
        current: list[str],
        requested: list[str],
    ) -> None:
        rejected = outside_roles_catalog(
            requested, organization_id=organization_id, catalog=deps.catalog
        )
        if rejected:
            raise bad_request(
                f"Roles não liberadas para a Organization: {', '.join(rejected)}.",
                field="roles",
            )
        can_bind = standing is not Standing.MEMBER or principal.has_permission(
            permissions.GROUP_BIND
        )
        if not binding_allowed(current, requested, principal.permissions, can_bind=can_bind):
            raise forbidden(
                f"É necessária a permissão {permissions.GROUP_BIND} para atribuir ou alterar"
                " roles de um grupo."
            )

    def check_version(record: ResourceRecord, version: str) -> None:
        if str(record.resource_version) != version:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Conflict",
                "O recurso mudou desde a leitura. Leia de novo e repita o pedido.",
            )

    # ------------------------------------------------------------ groups

    @app.post(
        "/v1/ipm/groups",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def create_group(
        body: generated.GroupCreateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ApiAcceptedResponse:
        require(principal, permissions.GROUP_CREATE)
        organization_id = body.organization_id
        standing = await standing_in(principal, organization_id)
        if standing is None:
            raise not_found()
        requested_roles = _roles_of(body.roles) if body.roles is not None else []
        check_roles(principal, standing, organization_id, [], requested_roles)
        quota: int | None = None
        if standing is not Standing.OPERATOR:
            quota = deps.settings.group_quota
            if await deps.repository.count_groups_in(organization_id) >= quota:
                raise ApiError(
                    HTTPStatus.FORBIDDEN,
                    "QuotaExceeded",
                    "Limite de grupos da Organization atingido.",
                )
        specification: dict[str, Any] = {
            "organizationId": organization_id,
            "name": str(body.name).strip(),
            "description": str(body.description).strip(),
            "roles": requested_roles,
            "deletionProtection": body.deletion_protection is True,
        }
        new_group_id = deps.identifiers()
        return await submit(
            deps,
            log_context={"organization_id": organization_id},
            resource_id=new_group_id,
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
        "/v1/ipm/groups/{group_id}",
        response_model=generated.Group,
        response_model_exclude_none=True,
    )
    async def get_group(group_id: str, principal: Authenticated) -> generated.Group:
        require(principal, permissions.GROUP_GET)
        record, _ = await visible_group(principal, group_id)
        return group_view(record)

    @app.get(
        "/v1/ipm/groups",
        response_model=generated.GroupList,
        response_model_exclude_none=True,
    )
    async def list_groups(
        principal: Authenticated,
        organization_id: OrganizationQuery,
        limit: Annotated[int, Query(ge=1, le=MAXIMUM_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        cursor: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9_-]{1,512}$")] = None,
    ) -> generated.GroupList:
        require(principal, permissions.GROUP_LIST)
        if await standing_in(principal, organization_id) is None:
            raise not_found()
        records = await deps.repository.list_groups(
            organization_id=organization_id, after=cursor, limit=limit + 1
        )
        page = records[:limit]
        payload: dict[str, Any] = {
            "items": [
                group_view(record).model_dump(mode="json", exclude_none=True) for record in page
            ]
        }
        if len(records) > limit:
            payload["nextCursor"] = page[-1].resource_id
        return generated.GroupList.model_validate(payload)

    @app.patch(
        "/v1/ipm/groups/{group_id}",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def update_group(
        group_id: str,
        body: generated.GroupUpdateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ApiAcceptedResponse:
        require(principal, permissions.GROUP_UPDATE)
        record, standing = await visible_group(principal, group_id)
        if not body.resource_version.isdigit():
            raise bad_request("resourceVersion deve ser numérico.", field="resourceVersion")
        specification: dict[str, Any] = {}
        if body.description is not None:
            specification["description"] = str(body.description).strip()
        if body.roles is not None:
            requested_roles = _roles_of(body.roles)
            current_roles = _roles_of(record.desired.get("roles"))
            check_roles(
                principal,
                standing,
                str(record.desired.get("organizationId", "")),
                current_roles,
                requested_roles,
            )
            specification["roles"] = requested_roles
        if body.deletion_protection is not None:
            specification["deletionProtection"] = body.deletion_protection
        reconciliation = body.reconciliation.value if body.reconciliation is not None else None
        if not specification and reconciliation is None:
            raise bad_request("Informe ao menos um campo a alterar.")
        if reconciliation is not None and standing is not Standing.OPERATOR:
            raise forbidden()
        check_version(record, body.resource_version)
        content: dict[str, Any] = {
            "operation": "update",
            "resourceId": group_id,
            "resourceVersion": body.resource_version,
        }
        data: dict[str, Any] = {"resourceVersion": body.resource_version}
        if specification:
            content["specification"] = data["specification"] = specification
        if reconciliation is not None:
            content["reconciliation"] = data["reconciliation"] = reconciliation
        return await submit(
            deps,
            log_context={"organization_id": str(record.desired.get("organizationId", ""))},
            resource_id=group_id,
            operation="update",
            requested_by=principal.subject,
            digest_content=content,
            extra_data=data,
            idempotency_key=idempotency_key,
        )

    @app.delete(
        "/v1/ipm/groups/{group_id}",
        status_code=202,
        response_model=generated.ApiAcceptedResponse,
        response_model_exclude_none=True,
    )
    async def delete_group(
        group_id: str,
        principal: Authenticated,
        resource_version: VersionQuery,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.ApiAcceptedResponse:
        require(principal, permissions.GROUP_DELETE)
        record, _ = await visible_group(principal, group_id)
        check_version(record, resource_version)
        if record.desired.get("deletionProtection", False) is True:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "DeletionProtected",
                "O grupo está protegido contra exclusão. Desproteja-o antes de excluir.",
            )
        # Verifica se há usuários da Organization associados a este grupo (decisão 0088)
        org_id = str(record.desired.get("organizationId", ""))
        group_name = str(record.desired.get("name", ""))
        attached_users = await deps.users.count_users_with_group(
            org_id, group_name, principal.access_token
        )
        if attached_users > 0:
            msg = (
                f"O grupo possui {attached_users} usuário(s) associado(s). "
                "Remova-os do grupo antes de excluir."
            )
            raise ApiError(HTTPStatus.CONFLICT, "ResourcesAttached", msg)
        return await submit(
            deps,
            log_context={"organization_id": org_id},
            resource_id=group_id,
            operation="delete",
            requested_by=principal.subject,
            digest_content={
                "operation": "delete",
                "resourceId": group_id,
                "resourceVersion": resource_version,
            },
            extra_data={"resourceVersion": resource_version},
            idempotency_key=idempotency_key,
        )

    # ------------------------------------------------------------ operations

    @app.get(
        "/v1/ipm/groups/{group_id}/operations/{operation_id}",
        response_model=generated.Operation,
        response_model_exclude_none=True,
    )
    async def get_operation(
        group_id: str, operation_id: str, principal: Authenticated
    ) -> generated.Operation:
        operation = await deps.repository.find_operation(operation_id)
        if operation is None or operation.resource_id != group_id:
            raise not_found()
        # O solicitante e os operadores leem a Operation mesmo depois de o grupo ser removido
        # (a espera de uma exclusão precisa ver o `completed`). Os demais precisam enxergar o grupo.
        if not (principal.is_operator or operation.requested_by == principal.subject):
            await visible_group(principal, group_id)
        return operation_view(operation)
