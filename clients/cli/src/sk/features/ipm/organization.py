"""Cliente do `ipm.organization` na API (`docs/loop/RESOURCE-CONTROL-LOOP.md` §6.1 e §46).

Criar, alterar e remover são escritas síncronas na admissão (decisão 0098): a API responde `201`,
`200` e `202` (na remoção) com o recurso, e a convergência se lê em `observedGeneration` e `phase`.
Não há Operation. Os dados chegam pelo mesmo `call_api`, com o token da sessão.
"""

import re
from dataclasses import dataclass
from typing import Any, cast

from sk.features.api_contract import as_object, as_text, validate_identifier
from sk.http import ApiUnavailableError, call_api

ORGANIZATIONS_PATH = "/v1/ipm/organizations"
# `organizationName` de `schemas/ipm/organization/definitions.v1.schema.json`: um rótulo DNS.
ORGANIZATION_NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
LIST_PAGE_SIZE = 200  # o máximo da API
MAXIMUM_LIST_PAGES = 50  # trava contra um cursor que nunca termina


@dataclass(frozen=True, slots=True)
class Organization:
    """Uma Organization, como a API a devolve ao dono (o `ownerAccountId` nunca é exposto)."""

    resource_id: str
    resource_version: str
    desired_generation: int
    observed_generation: int | None
    phase: str
    name: str
    lifecycle: str
    platform_access: str
    deletion_protection: bool
    """`True` impede a exclusão (decisão 0043); a API a devolve sempre, e ausente vale `True`."""
    organization_state: str | None
    """Estado lido do provedor (`active` ou `inactive`); `None` enquanto não foi observada."""
    billing_account_id: str | None = None
    """`resourceId` da Billing Account (`bsm.account`) vinculada à Organization, se informada."""
    failure_reason: str | None = None
    """Motivo da primeira condition `False`, quando houver (para explicar a fase `Failed`)."""


def validate_name(value: str) -> str:
    """Devolve o nome se ele segue o contrato, ou levanta `ValueError` (sem repetir o valor)."""
    if not ORGANIZATION_NAME_PATTERN.fullmatch(value):
        raise ValueError(
            "name invalid: use lowercase letters, digits and hyphen, starting and ending with a "
            "letter or digit (1 to 63 characters)"
        )
    return value


def _generation(body: dict[str, Any], key: str, *, required: bool) -> int | None:
    value = body.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if required or value is not None:
        raise ApiUnavailableError(f"API response without {key}: organization")
    return None


def _failure_reason(body: dict[str, Any]) -> str | None:
    conditions = body.get("conditions")
    if not isinstance(conditions, list):
        return None
    for item in cast("list[object]", conditions):
        if isinstance(item, dict):
            condition = cast("dict[str, object]", item)
            reason = condition.get("reason")
            if condition.get("status") == "False" and isinstance(reason, str):
                return reason
    return None


def _organization(document: object) -> Organization:
    body = as_object(document, what="organization")
    desired = as_object(body.get("desired"), what="organization (desired)")
    observed = as_object(body.get("observed") or {}, what="organization (observed)")
    state = observed.get("organizationState")
    billing_account_id = desired.get("billingAccountId")
    return Organization(
        resource_id=as_text(body, "resourceId", what="organization"),
        resource_version=as_text(body, "resourceVersion", what="organization"),
        desired_generation=cast("int", _generation(body, "desiredGeneration", required=True)),
        observed_generation=_generation(body, "observedGeneration", required=False),
        phase=as_text(body, "phase", what="organization"),
        name=as_text(desired, "name", what="organization (desired)"),
        lifecycle=as_text(desired, "lifecycle", what="organization (desired)"),
        platform_access=as_text(desired, "platformAccess", what="organization (desired)"),
        deletion_protection=desired.get("deletionProtection") is not False,
        organization_state=state if isinstance(state, str) else None,
        billing_account_id=billing_account_id if isinstance(billing_account_id, str) else None,
        failure_reason=_failure_reason(body),
    )


def create_organization(
    api_url: str,
    *,
    token: str,
    name: str,
    idempotency_key: str,
    allow_insecure_http: bool,
    billing_account_id: str | None = None,
) -> Organization:
    validate_name(name)
    body: dict[str, object] = {"name": name}
    if billing_account_id is not None:
        body["billingAccountId"] = validate_identifier(billing_account_id, what="billingAccountId")
    _, document = call_api(
        "POST",
        api_url,
        ORGANIZATIONS_PATH,
        token=token,
        body=body,
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return _organization(document)


def update_organization(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    name: str | None = None,
    billing_account_id: str | None = None,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> Organization:
    resource_id = validate_identifier(resource_id, what="resourceId")
    body: dict[str, object] = {"resourceVersion": resource_version}
    if name is not None:
        validate_name(name)
        body["name"] = name
    if billing_account_id is not None:
        body["billingAccountId"] = validate_identifier(billing_account_id, what="billingAccountId")
    _, document = call_api(
        "PATCH",
        api_url,
        f"{ORGANIZATIONS_PATH}/{resource_id}",
        token=token,
        body=body,
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return _organization(document)


def set_organization_protection(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    protected: bool,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> Organization:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "PATCH",
        api_url,
        f"{ORGANIZATIONS_PATH}/{resource_id}",
        token=token,
        body={"resourceVersion": resource_version, "deletionProtection": protected},
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return _organization(document)


def delete_organization(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> Organization:
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
    return _organization(document)


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
