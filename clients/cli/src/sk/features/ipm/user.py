"""Cliente do `ipm.user` na API da plataforma (decisão 0077).

Usuários da Organization: criados dentro dela, sem senha (a pessoa define a senha pelo e-mail de
ativação), com permissões da plataforma. Criar, alterar e remover são escritas assíncronas: a API
responde `202` com o `operationId`, e o estado definitivo vem do usuário (`phase`) e da Operation
(`operationStatus`). A leitura das respostas é estrita.
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

USERS_PATH = "/v1/ipm/users"
# `permission` de `schemas/ipm/user/definitions.v1.schema.json`: `<módulo>.<tipo>.<ação>`.
PERMISSION_PATTERN = re.compile(r"^[a-z][a-z0-9]*\.[a-z][a-z0-9]*\.[a-z][a-z0-9]*$")
MAXIMUM_PERMISSIONS = 64
# `roleName` de `schemas/ipm/user/definitions.v1.schema.json`: `<módulo>.<tipo><Admin|Viewer>`.
ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9]*\.[a-z][a-zA-Z0-9]*$")
MAXIMUM_ROLES = 32
GROUP_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,61}[a-z0-9]$")
MAXIMUM_GROUPS = 32
LIST_PAGE_SIZE = 200  # o máximo da API
MAXIMUM_LIST_PAGES = 50  # trava contra um cursor que nunca termina


@dataclass(frozen=True, slots=True)
class User:
    """Um usuário da Organization, como a API o devolve."""

    resource_id: str
    resource_version: str
    phase: str
    lifecycle: str
    organization_id: str
    email: str | None
    """Ausente depois do pedido de remoção (o `desired` deixa de ter dados pessoais)."""

    permissions: tuple[str, ...]
    deletion_protection: bool
    """`False` por padrão no usuário da Organization (decisão 0077)."""

    user_state: str | None
    """Estado lido do provedor (`initial` até a ativação); `None` enquanto não foi observado."""

    roles: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()


def validate_permissions(values: list[str]) -> list[str]:
    """Permissões sem repetição e em ordem, ou `ValueError` (sem repetir o valor recusado)."""
    permissions = sorted(set(values))
    if len(permissions) > MAXIMUM_PERMISSIONS:
        raise ValueError(f"too many permissions: at most {MAXIMUM_PERMISSIONS}")
    if any(not PERMISSION_PATTERN.fullmatch(permission) for permission in permissions):
        raise ValueError(
            "permission invalid: use <module>.<type>.<action>, for example ipm.user.get"
        )
    return permissions


def validate_roles(values: list[str]) -> list[str]:
    """Roles sem repetição e em ordem, ou `ValueError`."""
    roles = sorted(set(values))
    if len(roles) > MAXIMUM_ROLES:
        raise ValueError(f"too many roles: at most {MAXIMUM_ROLES}")
    if any(not ROLE_PATTERN.fullmatch(role) for role in roles):
        raise ValueError("role invalid: use <module>.<roleName>, for example ipm.userViewer")
    return roles


def validate_groups(values: list[str]) -> list[str]:
    """Grupos sem repetição e em ordem, ou `ValueError`."""
    groups = sorted(set(values))
    if len(groups) > MAXIMUM_GROUPS:
        raise ValueError(f"too many groups: at most {MAXIMUM_GROUPS}")
    if any(not GROUP_PATTERN.fullmatch(group) for group in groups):
        raise ValueError("group invalid: use lowercase slug (e.g. ops, sre-team)")
    return groups


def _user(document: object) -> User:
    body = as_object(document, what="user")
    desired = as_object(body.get("desired"), what="user (desired)")
    observed = as_object(body.get("observed") or {}, what="user (observed)")
    permissions: Any = desired.get("permissions")
    if not isinstance(permissions, list):
        raise ApiUnavailableError("API response without the user permissions")
    roles: Any = desired.get("roles")
    groups: Any = desired.get("groups")
    email = desired.get("email")
    state = observed.get("userState")
    return User(
        resource_id=as_text(body, "resourceId", what="user"),
        resource_version=as_text(body, "resourceVersion", what="user"),
        phase=as_text(body, "phase", what="user"),
        lifecycle=as_text(desired, "lifecycle", what="user (desired)"),
        organization_id=as_text(desired, "organizationId", what="user (desired)"),
        email=email if isinstance(email, str) else None,
        permissions=tuple(str(permission) for permission in cast("list[object]", permissions)),
        deletion_protection=desired.get("deletionProtection") is True,
        user_state=state if isinstance(state, str) else None,
        roles=tuple(str(role) for role in cast("list[object]", roles))
        if isinstance(roles, list)
        else (),
        groups=tuple(str(group) for group in cast("list[object]", groups))
        if isinstance(groups, list)
        else (),
    )


def create_user(
    api_url: str,
    *,
    token: str,
    organization_id: str,
    given_name: str,
    family_name: str,
    email: str,
    permissions: list[str] | None = None,
    roles: list[str] | None = None,
    groups: list[str] | None = None,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> RequestAccepted:
    organization_id = validate_identifier(organization_id, what="organizationId")
    body: dict[str, Any] = {
        "organizationId": organization_id,
        "givenName": given_name,
        "familyName": family_name,
        "email": email,
    }
    if permissions is not None:
        body["permissions"] = validate_permissions(permissions)
    if roles is not None:
        body["roles"] = validate_roles(roles)
    if groups is not None:
        body["groups"] = validate_groups(groups)
    _, document = call_api(
        "POST",
        api_url,
        USERS_PATH,
        token=token,
        body=body,
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return parse_accepted(document)


def update_user(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    permissions: list[str] | None = None,
    roles: list[str] | None = None,
    groups: list[str] | None = None,
    protected: bool | None = None,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> RequestAccepted:
    """Troca as permissões, as roles, os grupos e/ou a proteção contra exclusão."""
    resource_id = validate_identifier(resource_id, what="resourceId")
    body: dict[str, Any] = {"resourceVersion": resource_version}
    if permissions is not None:
        body["permissions"] = validate_permissions(permissions)
    if roles is not None:
        body["roles"] = validate_roles(roles)
    if groups is not None:
        body["groups"] = validate_groups(groups)
    if protected is not None:
        body["deletionProtection"] = protected
    _, document = call_api(
        "PATCH",
        api_url,
        f"{USERS_PATH}/{resource_id}",
        token=token,
        body=body,
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return parse_accepted(document)


def delete_user(
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
        f"{USERS_PATH}/{resource_id}",
        token=token,
        query={"resourceVersion": resource_version},
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return parse_accepted(document)


def get_user(api_url: str, *, token: str, resource_id: str, allow_insecure_http: bool) -> User:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "GET",
        api_url,
        f"{USERS_PATH}/{resource_id}",
        token=token,
        allow_insecure_http=allow_insecure_http,
    )
    return _user(document)


def list_users(
    api_url: str, *, token: str, organization_id: str, allow_insecure_http: bool
) -> list[User]:
    """Todos os usuários da Organization, seguindo o cursor das páginas."""
    organization_id = validate_identifier(organization_id, what="organizationId")
    found: list[User] = []
    cursor: str | None = None
    for _ in range(MAXIMUM_LIST_PAGES):
        query = {
            "organizationId": organization_id,
            "limit": str(LIST_PAGE_SIZE),
            **({"cursor": cursor} if cursor else {}),
        }
        _, document = call_api(
            "GET",
            api_url,
            USERS_PATH,
            token=token,
            query=query,
            allow_insecure_http=allow_insecure_http,
        )
        body = as_object(document, what="listing")
        items = body.get("items")
        if not isinstance(items, list):
            raise ApiUnavailableError("API response without items")
        found.extend(_user(item) for item in cast("list[object]", items))
        next_cursor = body.get("nextCursor")
        if not isinstance(next_cursor, str):
            return found
        cursor = next_cursor
    raise ApiUnavailableError("API listing did not end")


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
        f"{USERS_PATH}/{resource_id}/operations/{operation_id}",
        token=token,
        allow_insecure_http=allow_insecure_http,
    )
    return parse_operation(document)
