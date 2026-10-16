"""Cliente do `ipm.organization` na API da plataforma (`docs/RESOURCE-CONTROL-LOOP.md`, §6.1 e §46).

Criar, alterar e remover são escritas assíncronas: a API responde `202` com o `operationId`, e o
estado definitivo vem da Organization (`phase`) e da Operation (`operationStatus`). Os dados chegam
pelo mesmo `call_api`, com o token da sessão. A leitura das respostas é estrita.
"""

import re
from dataclasses import dataclass
from typing import cast

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

ORGANIZATIONS_PATH = "/v1/ipm/organizations"
# `organizationName` de `schemas/ipm/organization/definitions.v1.schema.json`: um rótulo DNS.
ORGANIZATION_NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
LIST_PAGE_SIZE = 200  # o máximo da API
MAXIMUM_LIST_PAGES = 50  # trava contra um cursor que nunca termina


@dataclass(frozen=True, slots=True)
class Organization:
    """Uma Organization, como a API a devolve ao dono (o `ownerUserId` nunca é exposto)."""

    resource_id: str
    resource_version: str
    phase: str
    name: str
    lifecycle: str
    platform_access: str
    organization_state: str | None
    """Estado lido do provedor (`active` ou `inactive`); `None` enquanto não foi observada."""


def validate_name(value: str) -> str:
    """Devolve o nome se ele segue o contrato, ou levanta `ValueError` (sem repetir o valor)."""
    if not ORGANIZATION_NAME_PATTERN.fullmatch(value):
        raise ValueError(
            "name invalid: use lowercase letters, digits and hyphen, starting and ending with a "
            "letter or digit (1 to 63 characters)"
        )
    return value


def _organization(document: object) -> Organization:
    body = as_object(document, what="organization")
    desired = as_object(body.get("desired"), what="organization (desired)")
    observed = as_object(body.get("observed") or {}, what="organization (observed)")
    state = observed.get("organizationState")
    return Organization(
        resource_id=as_text(body, "resourceId", what="organization"),
        resource_version=as_text(body, "resourceVersion", what="organization"),
        phase=as_text(body, "phase", what="organization"),
        name=as_text(desired, "name", what="organization (desired)"),
        lifecycle=as_text(desired, "lifecycle", what="organization (desired)"),
        platform_access=as_text(desired, "platformAccess", what="organization (desired)"),
        organization_state=state if isinstance(state, str) else None,
    )


def create_organization(
    api_url: str, *, token: str, name: str, idempotency_key: str, allow_insecure_http: bool
) -> RequestAccepted:
    validate_name(name)
    _, document = call_api(
        "POST",
        api_url,
        ORGANIZATIONS_PATH,
        token=token,
        body={"name": name},
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return parse_accepted(document)


def update_organization(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    name: str,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> RequestAccepted:
    resource_id = validate_identifier(resource_id, what="resourceId")
    validate_name(name)
    _, document = call_api(
        "PATCH",
        api_url,
        f"{ORGANIZATIONS_PATH}/{resource_id}",
        token=token,
        body={"resourceVersion": resource_version, "name": name},
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return parse_accepted(document)


def delete_organization(
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
        f"{ORGANIZATIONS_PATH}/{resource_id}",
        token=token,
        query={"resourceVersion": resource_version},
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return parse_accepted(document)


def get_organization(
    api_url: str, *, token: str, resource_id: str, allow_insecure_http: bool
) -> Organization:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "GET",
        api_url,
        f"{ORGANIZATIONS_PATH}/{resource_id}",
        token=token,
        allow_insecure_http=allow_insecure_http,
    )
    return _organization(document)


def list_organizations(
    api_url: str, *, token: str, allow_insecure_http: bool
) -> list[Organization]:
    """Todas as Organizations visíveis ao solicitante, seguindo o cursor das páginas."""
    found: list[Organization] = []
    cursor: str | None = None
    for _ in range(MAXIMUM_LIST_PAGES):
        query = {"limit": str(LIST_PAGE_SIZE), **({"cursor": cursor} if cursor else {})}
        _, document = call_api(
            "GET",
            api_url,
            ORGANIZATIONS_PATH,
            token=token,
            query=query,
            allow_insecure_http=allow_insecure_http,
        )
        body = as_object(document, what="listing")
        items = body.get("items")
        if not isinstance(items, list):
            raise ApiUnavailableError("API response without items")
        found.extend(_organization(item) for item in cast("list[object]", items))
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
        f"{ORGANIZATIONS_PATH}/{resource_id}/operations/{operation_id}",
        token=token,
        allow_insecure_http=allow_insecure_http,
    )
    return parse_operation(document)
