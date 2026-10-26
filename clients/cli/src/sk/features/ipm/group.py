"""Cliente do `ipm.group` na API da plataforma (decisão 0088).

Grupos de usuários da Organization: agrupadores de Roles compostas mantidos no SSOT da Smarkee
com estado materializado no banco `platform`.
Criar, alterar e remover são escritas assíncronas. A leitura das respostas é estrita.
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

GROUPS_PATH = "/v1/ipm/groups"
# `groupName` de `schemas/ipm/group/definitions.v1.schema.json`: slug curto.
GROUP_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,61}[a-z0-9]$")
# `roleName` de `schemas/ipm/group/definitions.v1.schema.json`: <módulo>.<papel>.
ROLE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*\.[a-z][a-zA-Z0-9]*$")
MAXIMUM_ROLES_PER_GROUP = 32
LIST_PAGE_SIZE = 200
MAXIMUM_LIST_PAGES = 50


@dataclass(frozen=True, slots=True)
class Group:
    """Um grupo de usuários da Organization, como a API o devolve."""

    resource_id: str
    resource_version: str
    phase: str
    lifecycle: str
    organization_id: str
    name: str
    description: str
    roles: tuple[str, ...]
    deletion_protection: bool
    status: str | None = None


def validate_group_name(name: str) -> str:
    """Nome do grupo em slug minúsculo, ou `ValueError`."""
    trimmed = name.strip()
    if not (2 <= len(trimmed) <= 63) or not GROUP_NAME_PATTERN.fullmatch(trimmed):
        raise ValueError(
            "group name invalid: use lowercase slug (2-63 chars, e.g. devops, sre-team)"
        )
    return trimmed


def validate_description(description: str, *, name: str | None = None) -> str:
    """Descrição em pt-BR do grupo, diferente do nome."""
    trimmed = description.strip()
    if not (1 <= len(trimmed) <= 256):
        raise ValueError("description must be between 1 and 256 characters")
    if name is not None and trimmed.lower() == name.strip().lower():
        raise ValueError("description must explain the group, not repeat its name")
    return trimmed


def validate_roles_list(values: list[str]) -> list[str]:
    """Lista de roles compostas válidas sem repetição e ordenadas."""
    roles = sorted(set(values))
    if len(roles) > MAXIMUM_ROLES_PER_GROUP:
        raise ValueError(f"too many roles: at most {MAXIMUM_ROLES_PER_GROUP}")
    if any(not ROLE_NAME_PATTERN.fullmatch(r) for r in roles):
        raise ValueError("role invalid: use <module>.<roleName>, for example ipm.userViewer")
    return roles


def _group(document: object) -> Group:
    body = as_object(document, what="group")
    desired = as_object(body.get("desired"), what="group (desired)")
    spec_obj = desired.get("specification")
    spec = (
        as_object(cast("dict[object, object]", spec_obj), what="group (specification)")
        if isinstance(spec_obj, dict)
        else desired
    )
    name = spec.get("name")
    if not isinstance(name, str):
        raise ApiUnavailableError("API response without the group name")
    description = spec.get("description")
    if not isinstance(description, str):
        raise ApiUnavailableError("API response without the group description")
    raw_roles = spec.get("roles")
    if not isinstance(raw_roles, list):
        raise ApiUnavailableError("API response without the group roles")
    return Group(
        resource_id=as_text(body, "resourceId", what="group"),
        resource_version=as_text(body, "resourceVersion", what="group"),
        phase=as_text(body, "phase", what="group"),
        lifecycle=as_text(desired, "lifecycle", what="group (desired)"),
        organization_id=as_text(desired, "organizationId", what="group (desired)"),
        name=name,
        description=description,
        roles=tuple(str(item) for item in cast("list[object]", raw_roles)),
        deletion_protection=spec.get("deletionProtection") is True,
        status=as_text(spec, "status", what="group (specification)") if "status" in spec else None,
    )


def create_group(
    api_url: str,
    *,
    token: str,
    organization_id: str,
    name: str,
    description: str,
    roles: list[str] | None = None,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> RequestAccepted:
    """Pede a criação de um grupo na Organization."""
    org_id = validate_identifier(organization_id, what="organizationId")
    valid_name = validate_group_name(name)
    valid_desc = validate_description(description, name=valid_name)
    valid_roles = validate_roles_list(roles or [])
    body: dict[str, Any] = {
        "organizationId": org_id,
        "name": valid_name,
        "description": valid_desc,
        "roles": valid_roles,
    }
    _, document = call_api(
        "POST",
        api_url,
        GROUPS_PATH,
        token=token,
        body=body,
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return parse_accepted(document)


def update_group(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    description: str | None = None,
    roles: list[str] | None = None,
    protected: bool | None = None,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> RequestAccepted:
    """Altera descrição, roles e/ou proteção contra exclusão."""
    resource_id = validate_identifier(resource_id, what="resourceId")
    body: dict[str, Any] = {"resourceVersion": resource_version}
    if description is not None:
        body["description"] = validate_description(description)
    if roles is not None:
        body["roles"] = validate_roles_list(roles)
    if protected is not None:
        body["deletionProtection"] = protected
    _, document = call_api(
        "PATCH",
        api_url,
        f"{GROUPS_PATH}/{resource_id}",
        token=token,
        body=body,
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return parse_accepted(document)


def set_group_protection(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    protected: bool,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> RequestAccepted:
    return update_group(
        api_url,
        token=token,
        resource_id=resource_id,
        resource_version=resource_version,
        protected=protected,
        idempotency_key=idempotency_key,
        allow_insecure_http=allow_insecure_http,
    )


def delete_group(
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
        f"{GROUPS_PATH}/{resource_id}",
        token=token,
        query={"resourceVersion": resource_version},
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return parse_accepted(document)


def get_group(api_url: str, *, token: str, resource_id: str, allow_insecure_http: bool) -> Group:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "GET",
        api_url,
        f"{GROUPS_PATH}/{resource_id}",
        token=token,
        allow_insecure_http=allow_insecure_http,
    )
    return _group(document)


def list_groups(
    api_url: str,
    *,
    token: str,
    organization_id: str,
    allow_insecure_http: bool,
) -> list[Group]:
    """Lista todos os grupos da Organization, seguindo o cursor `after`."""
    org_id = validate_identifier(organization_id, what="organizationId")
    found: list[Group] = []
    after: str | None = None
    for _ in range(MAXIMUM_LIST_PAGES):
        query = {
            "organizationId": org_id,
            "limit": str(LIST_PAGE_SIZE),
            **({"after": after} if after else {}),
        }
        _, document = call_api(
            "GET",
            api_url,
            GROUPS_PATH,
            token=token,
            query=query,
            allow_insecure_http=allow_insecure_http,
        )
        body = as_object(document, what="groups list")
        items = body.get("items")
        if not isinstance(items, list):
            raise ApiUnavailableError("API response without an items list")
        found.extend(_group(item) for item in cast("list[object]", items))
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
        f"{GROUPS_PATH}/{resource_id}/operations/{operation_id}",
        token=token,
        allow_insecure_http=allow_insecure_http,
    )
    return parse_operation(document)
