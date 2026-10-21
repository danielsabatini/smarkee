"""Cliente do `ipm.user` na API da plataforma (decisão 0077).

Usuários da Organization: criados dentro dela, sem senha (a pessoa define a senha pelo e-mail de
ativação), com roles da plataforma. Criar, alterar e remover são escritas assíncronas: a API
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
# `role` de `schemas/ipm/user/definitions.v1.schema.json`: `<módulo>.<tipo>.<ação>`.
ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9]*\.[a-z][a-z0-9]*\.[a-z][a-z0-9]*$")
MAXIMUM_ROLES = 64
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

    roles: tuple[str, ...]
    deletion_protection: bool
    """`False` por padrão no usuário da Organization (decisão 0077)."""

    user_state: str | None
    """Estado lido do provedor (`initial` até a ativação); `None` enquanto não foi observado."""


def validate_roles(values: list[str]) -> list[str]:
    """Roles sem repetição e em ordem, ou `ValueError` (sem repetir o valor recusado)."""
    roles = sorted(set(values))
    if len(roles) > MAXIMUM_ROLES:
        raise ValueError(f"too many roles: at most {MAXIMUM_ROLES}")
    if any(not ROLE_PATTERN.fullmatch(role) for role in roles):
        raise ValueError("role invalid: use <module>.<type>.<action>, for example ipm.user.get")
    return roles


def _user(document: object) -> User:
    body = as_object(document, what="user")
    desired = as_object(body.get("desired"), what="user (desired)")
    observed = as_object(body.get("observed") or {}, what="user (observed)")
    roles: Any = desired.get("roles")
    if not isinstance(roles, list):
        raise ApiUnavailableError("API response without the user roles")
    email = desired.get("email")
    state = observed.get("userState")
    return User(
        resource_id=as_text(body, "resourceId", what="user"),
        resource_version=as_text(body, "resourceVersion", what="user"),
        phase=as_text(body, "phase", what="user"),
        lifecycle=as_text(desired, "lifecycle", what="user (desired)"),
        organization_id=as_text(desired, "organizationId", what="user (desired)"),
        email=email if isinstance(email, str) else None,
        roles=tuple(str(role) for role in cast("list[object]", roles)),
        deletion_protection=desired.get("deletionProtection") is True,
        user_state=state if isinstance(state, str) else None,
    )


def create_user(
    api_url: str,
    *,
    token: str,
    organization_id: str,
    given_name: str,
    family_name: str,
    email: str,
    roles: list[str],
    idempotency_key: str,
    allow_insecure_http: bool,
) -> RequestAccepted:
    organization_id = validate_identifier(organization_id, what="organizationId")
    _, document = call_api(
        "POST",
        api_url,
        USERS_PATH,
        token=token,
        body={
            "organizationId": organization_id,
            "givenName": given_name,
            "familyName": family_name,
            "email": email,
            "roles": validate_roles(roles),
        },
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
    roles: list[str] | None = None,
    protected: bool | None = None,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> RequestAccepted:
    """Troca as roles (o conjunto inteiro) e/ou a proteção contra exclusão."""
    resource_id = validate_identifier(resource_id, what="resourceId")
    body: dict[str, Any] = {"resourceVersion": resource_version}
    if roles is not None:
        body["roles"] = validate_roles(roles)
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
