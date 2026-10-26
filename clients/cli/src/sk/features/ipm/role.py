"""Cliente do `ipm.role` na API da plataforma (decisões 0083 e 0092).

Roles compostas: agrupadores de permissões atômicas mantidos 100% no SSOT da Smarkee. As
`predefined` pertencem à plataforma (Organization `core`); as `custom` pertencem a uma
Organization. Criar, alterar e remover são escritas assíncronas. A leitura é estrita.
"""

import re
from dataclasses import dataclass
from typing import Any, cast

from sk.features.api_contract import (
    OperationStatus,
    RequestAccepted,
    as_object,
    as_text,
    parse_accepted,
    parse_operation,
    validate_identifier,
)
from sk.http import ApiUnavailableError, call_api

ROLES_PATH = "/v1/ipm/roles"
# `roleName` de `schemas/ipm/role/definitions.v1.schema.json`: <módulo>.<papel>.
ROLE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*\.[a-z][a-zA-Z0-9]*$")
# `permission` de `schemas/ipm/role/definitions.v1.schema.json`: <módulo>.<tipo>.<ação>.
PERMISSION_PATTERN = re.compile(r"^[a-z][a-z0-9]*\.[a-z][a-z0-9]*\.[a-z][a-z0-9]*$")
MAXIMUM_PERMISSIONS_PER_ROLE = 256
LIST_PAGE_SIZE = 200  # o máximo da API
MAXIMUM_LIST_PAGES = 50  # trava contra um cursor que nunca termina


@dataclass(frozen=True, slots=True)
class Role:
    """Uma role composta da plataforma, como a API a devolve."""

    resource_id: str
    resource_version: str
    phase: str
    lifecycle: str
    name: str
    description: str
    permissions: tuple[str, ...]
    deletion_protection: bool
    status: str | None = None
    """Status operacional do recurso ('active' ou 'inactive')."""
    organization_id: str = "core"
    """Organization dona da role; `core` são as predefinidas da plataforma."""
    role_type: str = "custom"
    """Natureza da role: 'predefined' (catálogo da plataforma) ou 'custom' (criada por pedido)."""


def validate_role_name(name: str) -> str:
    """Nome da role no padrão <módulo>.<papel>, ou `ValueError`."""
    trimmed = name.strip()
    if not (3 <= len(trimmed) <= 128) or not ROLE_NAME_PATTERN.fullmatch(trimmed):
        raise ValueError("role name invalid: use <module>.<roleName>, for example ipm.userAdmin")
    return trimmed


def validate_description(description: str, *, name: str | None = None) -> str:
    """Descrição em pt-BR da role, diferente do nome."""
    trimmed = description.strip()
    if not (1 <= len(trimmed) <= 256):
        raise ValueError("description must be between 1 and 256 characters")
    if name is not None and trimmed.lower() == name.strip().lower():
        raise ValueError("description must explain the role, not repeat its name")
    return trimmed


def validate_permissions_list(values: list[str]) -> list[str]:
    """Lista não vazia de permissões atômicas válidas sem repetição e ordenadas."""
    if not values:
        raise ValueError("role must have at least one permission")
    perms = sorted(set(values))
    if len(perms) > MAXIMUM_PERMISSIONS_PER_ROLE:
        raise ValueError(f"too many permissions: at most {MAXIMUM_PERMISSIONS_PER_ROLE}")
    if any(not PERMISSION_PATTERN.fullmatch(p) for p in perms):
        raise ValueError(
            "permission invalid: use <module>.<type>.<action>, for example ipm.user.get"
        )
    return perms


def _role(document: object) -> Role:
    body = as_object(document, what="role")
    desired = as_object(body.get("desired"), what="role (desired)")
    spec_obj = desired.get("specification")
    spec = (
        as_object(cast(object, spec_obj), what="role (specification)")
        if isinstance(spec_obj, dict)
        else desired
    )
    name = spec.get("name")
    if not isinstance(name, str):
        raise ApiUnavailableError("API response without the role name")
    description = spec.get("description")
    if not isinstance(description, str):
        raise ApiUnavailableError("API response without the role description")
    raw_permissions = spec.get("permissions")
    if not isinstance(raw_permissions, list):
        raise ApiUnavailableError("API response without the role permissions")
    return Role(
        resource_id=as_text(body, "resourceId", what="role"),
        resource_version=as_text(body, "resourceVersion", what="role"),
        phase=as_text(body, "phase", what="role"),
        lifecycle=as_text(desired, "lifecycle", what="role (desired)"),
        name=name,
        description=description,
        permissions=tuple(str(item) for item in cast("list[object]", raw_permissions)),
        deletion_protection=spec.get("deletionProtection") is True,
        status=as_text(spec, "status", what="role (specification)") if "status" in spec else None,
        organization_id=str(desired.get("organizationId") or "core"),
        role_type=str(spec.get("roleType") or "custom"),
    )


def create_role(
    api_url: str,
    *,
    token: str,
    organization_id: str,
    name: str,
    description: str,
    permissions: list[str],
    idempotency_key: str,
    allow_insecure_http: bool,
) -> RequestAccepted:
    """Pede a criação de uma role `custom` na Organization (requer ipm.role.create)."""
    org_id = validate_identifier(organization_id, what="organizationId")
    valid_name = validate_role_name(name)
    valid_desc = validate_description(description, name=valid_name)
    valid_perms = validate_permissions_list(permissions)
    _, document = call_api(
        "POST",
        api_url,
        ROLES_PATH,
        token=token,
        body={
            "organizationId": org_id,
            "name": valid_name,
            "description": valid_desc,
            "permissions": valid_perms,
        },
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return parse_accepted(document)


def update_role(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    description: str | None = None,
    permissions: list[str] | None = None,
    protected: bool | None = None,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> RequestAccepted:
    """Altera descrição, permissões e/ou proteção contra exclusão."""
    resource_id = validate_identifier(resource_id, what="resourceId")
    body: dict[str, Any] = {"resourceVersion": resource_version}
    if description is not None:
        body["description"] = validate_description(description)
    if permissions is not None:
        body["permissions"] = validate_permissions_list(permissions)
    if protected is not None:
        body["deletionProtection"] = protected
    _, document = call_api(
        "PATCH",
        api_url,
        f"{ROLES_PATH}/{resource_id}",
        token=token,
        body=body,
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return parse_accepted(document)


def set_role_protection(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    protected: bool,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> RequestAccepted:
    return update_role(
        api_url,
        token=token,
        resource_id=resource_id,
        resource_version=resource_version,
        protected=protected,
        idempotency_key=idempotency_key,
        allow_insecure_http=allow_insecure_http,
    )


def delete_role(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> RequestAccepted:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "DELETE",
        api_url,
        f"{ROLES_PATH}/{resource_id}",
        token=token,
        query={"resourceVersion": resource_version},
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return parse_accepted(document)


def get_role(api_url: str, *, token: str, resource_id: str, allow_insecure_http: bool) -> Role:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "GET",
        api_url,
        f"{ROLES_PATH}/{resource_id}",
        token=token,
        allow_insecure_http=allow_insecure_http,
    )
    return _role(document)


def list_roles(
    api_url: str,
    *,
    token: str,
    organization_id: str | None = None,
    allow_insecure_http: bool,
) -> list[Role]:
    """Lista as roles predefinidas e, com `organization_id`, as `custom` dessa Organization."""
    if organization_id is not None:
        organization_id = validate_identifier(organization_id, what="organizationId")
    found: list[Role] = []
    after: str | None = None
    for _ in range(MAXIMUM_LIST_PAGES):
        query = {
            "limit": str(LIST_PAGE_SIZE),
            **({"organizationId": organization_id} if organization_id else {}),
            **({"after": after} if after else {}),
        }
        _, document = call_api(
            "GET",
            api_url,
            ROLES_PATH,
            token=token,
            query=query,
            allow_insecure_http=allow_insecure_http,
        )
        body = as_object(document, what="roles list")
        items = body.get("items")
        if not isinstance(items, list):
            raise ApiUnavailableError("API response without an items list")
        found.extend(_role(item) for item in cast("list[object]", items))
        after = body.get("nextCursor")
        if not isinstance(after, str) or not after:
            break
    return found


def get_operation(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    operation_id: str,
    allow_insecure_http: bool,
) -> OperationStatus:
    resource_id = validate_identifier(resource_id, what="resourceId")
    operation_id = validate_identifier(operation_id, what="operationId")
    _, document = call_api(
        "GET",
        api_url,
        f"{ROLES_PATH}/{resource_id}/operations/{operation_id}",
        token=token,
        allow_insecure_http=allow_insecure_http,
    )
    return parse_operation(document)
