"""Cliente do `ipm.serviceaccount` na API da plataforma (decisão 0094).

Service accounts da Organization: identidades de máquina criadas dentro dela, sem e-mail e sem
senha, autenticadas por chave assimétrica (par RSA gerado no cliente). Criar, alterar e remover são
escritas síncronas na admissão (decisão 0098): a API devolve o recurso (`201`, `200` e `202` na
remoção), e a convergência se lê em `observedGeneration` e `phase`. Não há Operation.
"""

import re
from dataclasses import dataclass
from typing import Any, cast

from sk.features.api_contract import as_object, as_text, validate_identifier
from sk.http import ApiUnavailableError, call_api

SERVICEACCOUNTS_PATH = "/v1/ipm/serviceaccounts"

# `name` de `schemas/ipm/serviceaccount/definitions.v1.schema.json`.
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,61}[a-z0-9]$")
# `roleName` de `schemas/ipm/serviceaccount/definitions.v1.schema.json`: `<módulo>.<roleName>`.
ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9]*\.[a-z][a-zA-Z0-9]*$")
MAXIMUM_ROLES = 32
MAXIMUM_KEYS = 3
LIST_PAGE_SIZE = 200
MAXIMUM_LIST_PAGES = 50


@dataclass(frozen=True, slots=True)
class ServiceAccountKey:
    """Uma chave da service account, lida do provedor pelo Observer."""

    key_id: str | None
    fingerprint: str
    expires_at: str | None
    status: str


@dataclass(frozen=True, slots=True)
class ServiceAccount:
    """Uma service account da Organization, como a API a devolve."""

    resource_id: str
    resource_version: str
    desired_generation: int
    observed_generation: int | None
    phase: str
    lifecycle: str
    organization_id: str
    name: str
    description: str | None
    roles: tuple[str, ...]
    permissions: tuple[str, ...]
    deletion_protection: bool
    keys: tuple[ServiceAccountKey, ...]
    desired_keys: tuple[dict[str, str], ...] = ()
    failure_reason: str | None = None
    """Motivo da primeira condition `False`, quando houver (para explicar a fase `Failed`)."""


def validate_name(value: str) -> str:
    """Valida o nome da service account."""
    name = value.strip()
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "name invalid: use 2-63 lowercase alphanumeric characters or hyphens, "
            "starting with a letter and ending with a letter or digit (e.g. ci-deployer)"
        )
    return name


def validate_roles(values: list[str]) -> list[str]:
    """Roles sem repetição e em ordem, ou `ValueError`."""
    roles = sorted(set(values))
    if len(roles) > MAXIMUM_ROLES:
        raise ValueError(f"too many roles: at most {MAXIMUM_ROLES}")
    if any(not ROLE_PATTERN.fullmatch(role) for role in roles):
        raise ValueError(
            "role invalid: use <module>.<roleName>, for example ipm.serviceaccountViewer"
        )
    return roles


def _key(document: object) -> ServiceAccountKey:
    data = as_object(document, what="serviceaccount key")
    key_id = data.get("keyId")
    expires_at = data.get("expiresAt")
    return ServiceAccountKey(
        key_id=str(key_id) if isinstance(key_id, str) and key_id else None,
        fingerprint=as_text(data, "fingerprint", what="serviceaccount key fingerprint"),
        expires_at=str(expires_at) if isinstance(expires_at, str) and expires_at else None,
        status=as_text(data, "status", what="serviceaccount key status"),
    )


def _generation(body: dict[str, Any], key: str, *, required: bool) -> int | None:
    value = body.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if required or value is not None:
        raise ApiUnavailableError(f"API response without {key}: serviceaccount")
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


def _serviceaccount(document: object) -> ServiceAccount:
    body = as_object(document, what="serviceaccount")
    desired = as_object(body.get("desired"), what="serviceaccount (desired)")
    observed = as_object(body.get("observed") or {}, what="serviceaccount (observed)")
    # Calculadas pelo Controller (decisão 0097); ausentes até a service account ser observada.
    permissions: Any = observed.get("effectivePermissions")
    roles: Any = desired.get("roles")
    description = desired.get("description")
    observed_keys = observed.get("keys")
    desired_keys = desired.get("keys")

    keys: list[ServiceAccountKey] = []
    if isinstance(observed_keys, list):
        keys = [_key(k) for k in cast("list[object]", observed_keys)]

    parsed_desired_keys: list[dict[str, str]] = []
    if isinstance(desired_keys, list):
        for item in cast("list[object]", desired_keys):
            if isinstance(item, dict):
                item_dict = cast("dict[str, object]", item)
                parsed_desired_keys.append({key: str(val) for key, val in item_dict.items()})

    return ServiceAccount(
        resource_id=as_text(body, "resourceId", what="serviceaccount"),
        resource_version=as_text(body, "resourceVersion", what="serviceaccount"),
        desired_generation=cast("int", _generation(body, "desiredGeneration", required=True)),
        observed_generation=_generation(body, "observedGeneration", required=False),
        phase=as_text(body, "phase", what="serviceaccount"),
        lifecycle=as_text(desired, "lifecycle", what="serviceaccount (desired)"),
        organization_id=as_text(desired, "organizationId", what="serviceaccount (desired)"),
        name=as_text(desired, "name", what="serviceaccount (desired)"),
        description=str(description) if isinstance(description, str) and description else None,
        roles=tuple(str(role) for role in cast("list[object]", roles))
        if isinstance(roles, list)
        else (),
        permissions=tuple(str(permission) for permission in cast("list[object]", permissions))
        if isinstance(permissions, list)
        else (),
        deletion_protection=desired.get("deletionProtection") is True,
        keys=tuple(keys),
        desired_keys=tuple(parsed_desired_keys),
        failure_reason=_failure_reason(body),
    )


def create_serviceaccount(
    api_url: str,
    *,
    token: str,
    organization_id: str,
    name: str,
    public_key: str,
    expires_at: str,
    description: str | None = None,
    roles: list[str] | None = None,
    deletion_protection: bool = True,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> ServiceAccount:
    """Cria a service account: a API a admite e devolve o recurso (`201`)."""
    organization_id = validate_identifier(organization_id, what="organizationId")
    validated_name = validate_name(name)
    body: dict[str, Any] = {
        "organizationId": organization_id,
        "name": validated_name,
        "deletionProtection": deletion_protection,
        "keys": [{"publicKey": public_key, "expiresAt": expires_at}],
    }
    if description:
        body["description"] = description
    if roles is not None:
        body["roles"] = validate_roles(roles)
    _, document = call_api(
        "POST",
        api_url,
        SERVICEACCOUNTS_PATH,
        token=token,
        body=body,
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return _serviceaccount(document)


def update_serviceaccount(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    description: str | None = None,
    roles: list[str] | None = None,
    deletion_protection: bool | None = None,
    keys: list[dict[str, str]] | None = None,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> ServiceAccount:
    """Altera papéis, descrição, proteção ou chaves públicas; devolve o recurso (`200`)."""
    resource_id = validate_identifier(resource_id, what="resourceId")
    body: dict[str, Any] = {"resourceVersion": resource_version}
    if description is not None:
        body["description"] = description
    if roles is not None:
        body["roles"] = validate_roles(roles)
    if deletion_protection is not None:
        body["deletionProtection"] = deletion_protection
    if keys is not None:
        body["keys"] = keys
    _, document = call_api(
        "PATCH",
        api_url,
        f"{SERVICEACCOUNTS_PATH}/{resource_id}",
        token=token,
        body=body,
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return _serviceaccount(document)


def delete_serviceaccount(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> ServiceAccount:
    """Pede a remoção: a API a admite e devolve o recurso em `Deleting` (`202`)."""
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "DELETE",
        api_url,
        f"{SERVICEACCOUNTS_PATH}/{resource_id}",
        token=token,
        query={"resourceVersion": resource_version},
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return _serviceaccount(document)


def get_serviceaccount(
    api_url: str, *, token: str, resource_id: str, allow_insecure_http: bool
) -> ServiceAccount:
    """Lê uma service account por resourceId."""
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "GET",
        api_url,
        f"{SERVICEACCOUNTS_PATH}/{resource_id}",
        token=token,
        allow_insecure_http=allow_insecure_http,
    )
    return _serviceaccount(document)


def list_serviceaccounts(
    api_url: str, *, token: str, organization_id: str, allow_insecure_http: bool
) -> list[ServiceAccount]:
    """Lista todas as service accounts da Organization, percorrendo todas as páginas."""
    organization_id = validate_identifier(organization_id, what="organizationId")
    found: list[ServiceAccount] = []
    cursor: str | None = None
    for _ in range(MAXIMUM_LIST_PAGES):
        query = {
            "organizationId": organization_id,
            "limit": str(LIST_PAGE_SIZE),
        }
        if cursor is not None:
            query["cursor"] = cursor
        _, document = call_api(
            "GET",
            api_url,
            SERVICEACCOUNTS_PATH,
            token=token,
            query=query,
            allow_insecure_http=allow_insecure_http,
        )
        body = as_object(document, what="serviceaccounts list")
        items = body.get("items")
        if not isinstance(items, list):
            raise ApiUnavailableError("API response without the serviceaccounts list")
        for item in cast("list[object]", items):
            found.append(_serviceaccount(item))
        next_cursor = body.get("nextCursor")
        if not isinstance(next_cursor, str) or not next_cursor:
            break
        cursor = next_cursor
    return found
