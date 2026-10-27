"""Aplicação HTTP da API (decisão 0098; `docs/loop/RESOURCE-CONTROL-LOOP.md` §6).

A API autentica, autoriza, valida e **admite a escrita de forma síncrona**: numa transação do SSOT
grava o recurso e o `desired` no outbox (o Publisher publica depois). Não há Operation: `POST`
responde `201`, `PATCH` responde `200` e `DELETE` responde `202`, todos com o `Resource`; a
convergência se acompanha lendo o recurso (`observedGeneration`, `phase` e `conditions`). Ela não
tem credencial no provedor de identidade. As leituras vêm das views do SSOT.

Escopo por Organization (decisão 0077): o operador age em qualquer uma; o dono (root), os usuários
e as service accounts da Organization, só nela. O usuário é reconhecido pelo próprio registro no
SSOT do tipo; o dono, pelo Receiver da Organization, com o token de quem pede (decisão 0040); a
service account, pela API de ServiceAccount (decisão 0094).
"""

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Any, Literal, Protocol

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ipm_user.api.domain import principal as permissions
from ipm_user.api.domain.access import (
    OrganizationAccess,
    binding_allowed,
    outside_groups_catalog,
    outside_roles_catalog,
)
from ipm_user.api.domain.admission import Admission
from ipm_user.api.domain.errors import (
    ApiError,
    bad_request,
    conflict,
    forbidden,
    not_found,
    unauthorized,
)
from ipm_user.api.domain.principal import Principal
from ipm_user.api.domain.records import ResourceRecord
from ipm_user.api.domain.requests import checked_idempotency_key, request_digest
from ipm_user.api.domain.views import user_view
from ipm_user.api.http.admission import admit
from ipm_user.api.http.health_routes import register_health_routes
from ipm_user.api.http.ports import AdmissionStore, Members, Organizations, Repository
from ipm_user.api.http.trace_context import TraceContextMiddleware
from ipm_user.api.settings import ApiSettings
from ipm_user.common.catalog import AccessCatalog
from ipm_user.common.contracts import generated
from ipm_user.common.ids import new_identifier, utc_now
from ipm_user.common.logging_config import bind_context

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 50
MAXIMUM_PAGE_SIZE = 200
RETRY_AFTER_SECONDS = "5"
RESOURCE_ID_PATTERN = r"^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$"
"""Padrão do `resourceId` (`schemas/common/definitions`)."""


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
    members: Members
    admissions: AdmissionStore
    catalog: AccessCatalog = field(default_factory=AccessCatalog)
    is_catalog_synced: Callable[[], bool] = lambda: True
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
OrganizationQuery = Annotated[str, Query(alias="organizationId", pattern=RESOURCE_ID_PATTERN)]


def create_app(deps: Dependencies) -> FastAPI:
    app = FastAPI(title="smarkee ipm user api", docs_url=None, redoc_url=None, openapi_url=None)
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


def _roles_of(values: Iterable[generated.RoleName | str] | None) -> list[str]:
    """Roles sem repetição e em ordem alfabética, como no contrato (decisão 0083)."""
    return sorted({value if isinstance(value, str) else value.root for value in values or []})


def _groups_of(values: Iterable[generated.GroupName | str] | None) -> list[str]:
    """Grupos sem repetição e em ordem alfabética (decisão 0088)."""
    return sorted({value if isinstance(value, str) else value.root for value in values or []})


# ---------------------------------------------------------------------- rotas


def _register_routes(app: FastAPI, deps: Dependencies) -> None:
    def require(principal: Principal, permission: str) -> None:
        if not principal.has_permission(permission):
            raise forbidden()

    async def standing_in(principal: Principal, organization_id: str) -> Standing | None:
        """Relação do solicitante com a Organization, ou `None` quando ele não age nela."""
        if principal.is_operator:
            return Standing.OPERATOR
        own = await deps.repository.get_user(principal.subject)
        if own is not None:
            # Um usuário da Organization age só nela, enquanto o próprio registro existir.
            belongs = (
                own.lifecycle == "present" and own.desired.get("organizationId") == organization_id
            )
            return Standing.MEMBER if belongs else None
        # Identidade de máquina da Organization (decisão 0094): age só na Organization dela.
        machine_organization = deps.members.organization_of(principal.subject)
        if machine_organization is not None:
            return Standing.MEMBER if machine_organization == organization_id else None
        access = deps.organizations.access(organization_id, principal.subject)
        return Standing.OWNER if access is OrganizationAccess.OWNED else None

    async def visible_user(principal: Principal, user_id: str) -> tuple[ResourceRecord, Standing]:
        record = await deps.repository.get_user(user_id)
        if record is None:
            raise not_found()
        standing = await standing_in(principal, str(record.desired.get("organizationId", "")))
        if standing is None:
            raise not_found()  # não revela usuários de outras Organizations
        return record, standing

    def _check_catalog_synced() -> None:
        if not deps.is_catalog_synced():
            raise ApiError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "CatalogSyncPending",
                "Catálogo de permissões em sincronização. Tente de novo em instantes.",
                headers={"Retry-After": "2"},
            )

    def check_roles(
        principal: Principal,
        standing: Standing,
        organization_id: str,
        current: list[str],
        requested: list[str],
    ) -> None:
        if requested:
            _check_catalog_synced()
        rejected = outside_roles_catalog(
            requested, organization_id=organization_id, catalog=deps.catalog
        )
        if rejected:
            raise bad_request(
                f"Roles não liberadas para a Organization: {', '.join(rejected)}.",
                field="roles",
            )
        can_bind = standing is not Standing.MEMBER or principal.has_permission(
            permissions.USER_BIND
        )
        if not binding_allowed(current, requested, principal.permissions, can_bind=can_bind):
            raise forbidden(
                f"É necessária a permissão {permissions.USER_BIND} para atribuir ou alterar"
                " roles de um usuário."
            )

    def check_groups(
        principal: Principal,
        standing: Standing,
        organization_id: str,
        current: list[str],
        requested: list[str],
    ) -> None:
        if requested:
            _check_catalog_synced()
        rejected = outside_groups_catalog(
            requested, organization_id=organization_id, catalog=deps.catalog
        )
        if rejected:
            raise bad_request(
                f"Grupos não encontrados na Organization: {', '.join(rejected)}.",
                field="groups",
            )
        can_bind = standing is not Standing.MEMBER or principal.has_permission(
            permissions.USER_BIND
        )
        if not binding_allowed(current, requested, principal.permissions, can_bind=can_bind):
            raise forbidden(
                f"É necessária a permissão {permissions.USER_BIND} para atribuir ou alterar"
                " grupos de um usuário."
            )

    def check_version(record: ResourceRecord, version: str) -> None:
        if str(record.resource_version) != version:
            raise conflict()

    async def admitted(admission: Admission) -> generated.User:
        return user_view(await admit(deps.admissions, admission))

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

    # ------------------------------------------------------------ users

    @app.post(
        "/v1/ipm/users",
        status_code=201,
        response_model=generated.User,
        response_model_exclude_none=True,
    )
    async def create_user(
        body: generated.UserCreateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.User:
        require(principal, permissions.USER_CREATE)
        organization_id = body.organization_id
        standing = await standing_in(principal, organization_id)
        if standing is None:
            raise not_found()
        requested_roles = _roles_of(body.roles) if body.roles is not None else []
        requested_groups = _groups_of(body.groups) if body.groups is not None else []
        check_roles(principal, standing, organization_id, [], requested_roles)
        check_groups(principal, standing, organization_id, [], requested_groups)
        quota: int | None = None
        if standing is not Standing.OPERATOR:
            quota = deps.settings.user_quota
        specification: dict[str, Any] = {
            "organizationId": organization_id,
            "givenName": body.given_name,
            "familyName": body.family_name,
            # O e-mail é também o nome de login na organização: normalizado (decisão 0077).
            "email": str(body.email).strip().lower(),
            "roles": requested_roles,
            "groups": requested_groups,
            # No usuário da Organization a proteção contra exclusão nasce desligada (decisão 0077).
            "deletionProtection": body.deletion_protection is True,
        }
        bind_context(organization_id=organization_id)
        return await admitted(
            admission_for(
                principal,
                "create",
                deps.identifiers(),
                idempotency_key,
                {"operation": "create", "specification": specification},
                specification=specification,
                quota_limit=quota,
            )
        )

    @app.get(
        "/v1/ipm/users/{user_id}",
        response_model=generated.User,
        response_model_exclude_none=True,
    )
    async def get_user(user_id: str, principal: Authenticated) -> generated.User:
        if user_id == principal.subject:
            # Todo usuário lê o próprio registro, sem permissão adicional (como o
            # `SelfSubjectReview` do Kubernetes): é assim que o Receiver da Organization
            # reconhece os usuários dela.
            record = await deps.repository.get_user(user_id)
            if record is None:
                raise not_found()
            return user_view(record)
        require(principal, permissions.USER_GET)
        record, _ = await visible_user(principal, user_id)
        return user_view(record)

    @app.get(
        "/v1/ipm/users",
        response_model=generated.UserList,
        response_model_exclude_none=True,
    )
    async def list_users(
        principal: Authenticated,
        organization_id: OrganizationQuery,
        limit: Annotated[int, Query(ge=1, le=MAXIMUM_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        cursor: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9_-]{1,512}$")] = None,
    ) -> generated.UserList:
        require(principal, permissions.USER_LIST)
        if await standing_in(principal, organization_id) is None:
            raise not_found()
        records = await deps.repository.list_users(
            organization_id=organization_id, after=cursor, limit=limit + 1
        )
        page = records[:limit]
        payload: dict[str, Any] = {
            "items": [
                user_view(record).model_dump(mode="json", exclude_none=True) for record in page
            ]
        }
        if len(records) > limit:
            payload["nextCursor"] = page[-1].resource_id
        return generated.UserList.model_validate(payload)

    @app.patch(
        "/v1/ipm/users/{user_id}",
        status_code=200,
        response_model=generated.User,
        response_model_exclude_none=True,
    )
    async def update_user(
        user_id: str,
        body: generated.UserUpdateRequest,
        principal: Authenticated,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.User:
        require(principal, permissions.USER_UPDATE)
        record, standing = await visible_user(principal, user_id)
        if not body.resource_version.isdigit():
            raise bad_request("resourceVersion deve ser numérico.", field="resourceVersion")
        organization_id = str(record.desired.get("organizationId", ""))
        specification: dict[str, Any] = {}
        if body.roles is not None:
            requested_roles = _roles_of(body.roles)
            current_roles = _roles_of(record.desired.get("roles"))
            check_roles(principal, standing, organization_id, current_roles, requested_roles)
            specification["roles"] = requested_roles
        if body.groups is not None:
            requested_groups = _groups_of(body.groups)
            current_groups = _groups_of(record.desired.get("groups"))
            check_groups(principal, standing, organization_id, current_groups, requested_groups)
            specification["groups"] = requested_groups
        if body.deletion_protection is not None:
            specification["deletionProtection"] = body.deletion_protection
        reconciliation = body.reconciliation.value if body.reconciliation is not None else None
        if not specification and reconciliation is None:
            raise bad_request("Informe ao menos um campo a alterar.")
        # O controle da reconciliação é privilégio de operador.
        if reconciliation is not None and standing is not Standing.OPERATOR:
            raise forbidden()
        check_version(record, body.resource_version)
        content: dict[str, Any] = {
            "operation": "update",
            "resourceId": user_id,
            "resourceVersion": body.resource_version,
        }
        if specification:
            content["specification"] = specification
        if reconciliation is not None:
            content["reconciliation"] = reconciliation
        bind_context(organization_id=organization_id)
        return await admitted(
            admission_for(
                principal,
                "update",
                user_id,
                idempotency_key,
                content,
                resource_version=int(body.resource_version),
                specification=specification,
                reconciliation=reconciliation,
            )
        )

    @app.delete(
        "/v1/ipm/users/{user_id}",
        status_code=202,
        response_model=generated.User,
        response_model_exclude_none=True,
    )
    async def delete_user(
        user_id: str,
        principal: Authenticated,
        resource_version: VersionQuery,
        idempotency_key: IdempotencyKey = None,
    ) -> generated.User:
        require(principal, permissions.USER_DELETE)
        record, _ = await visible_user(principal, user_id)
        check_version(record, resource_version)
        # No usuário da Organization a proteção nasce desligada (decisão 0077); ligada, recusa.
        if record.desired.get("deletionProtection", False) is True:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "DeletionProtected",
                "O usuário está protegido contra exclusão. Desproteja-o antes de excluir.",
            )
        bind_context(organization_id=str(record.desired.get("organizationId", "")))
        return await admitted(
            admission_for(
                principal,
                "delete",
                user_id,
                idempotency_key,
                {
                    "operation": "delete",
                    "resourceId": user_id,
                    "resourceVersion": resource_version,
                },
                resource_version=int(resource_version),
            )
        )
