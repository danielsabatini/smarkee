"""Cliente do `ipm.permission` na API da plataforma (decisões 0083 e 0098).

Permissões atômicas da plataforma no padrão `<módulo>.<tipo>.<ação>`. Criar, alterar e remover são
escritas síncronas do operador (`ipm.permission.admin`): a API responde `201`, `200` e `202` (na
remoção) com o recurso, e a convergência se lê em `observedGeneration` e `phase`. Não há Operation.
A leitura das respostas é estrita.
"""

import re
from dataclasses import dataclass
from typing import Any, cast

from sk.features.api_contract import as_object, as_text, validate_identifier
from sk.http import ApiUnavailableError, call_api

PERMISSIONS_PATH = "/v1/ipm/permissions"
# `permissionName` de `schemas/ipm/permission/definitions.v1.schema.json`: <módulo>.<tipo>.<ação>.
PERMISSION_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*\.[a-z][a-z0-9]*\.[a-z][a-z0-9]*$")
LIST_PAGE_SIZE = 200  # o máximo da API
MAXIMUM_LIST_PAGES = 50  # trava contra um cursor que nunca termina


@dataclass(frozen=True, slots=True)
class Permission:
    """Uma permissão atômica da plataforma, como a API a devolve."""

    resource_id: str
    resource_version: str
    desired_generation: int
    observed_generation: int | None
    phase: str
    lifecycle: str
    name: str
    description: str
    grantable: bool
    deletion_protection: bool
    status: str | None = None
    """Status operacional do recurso ('active' ou 'inactive')."""
    failure_reason: str | None = None
    """Motivo da primeira condition `False`, quando houver (para explicar a fase `Failed`)."""


def validate_permission_name(name: str) -> str:
    """Nome da permissão no padrão <módulo>.<tipo>.<ação>, ou `ValueError`."""
    trimmed = name.strip()
    if not (5 <= len(trimmed) <= 128) or not PERMISSION_NAME_PATTERN.fullmatch(trimmed):
        raise ValueError(
            "permission name invalid: use <module>.<type>.<action>, for example ipm.user.get"
        )
    return trimmed


def validate_description(description: str, *, name: str | None = None) -> str:
    """Descrição em pt-BR da ação autorizada, diferente do nome."""
    trimmed = description.strip()
    if not (1 <= len(trimmed) <= 256):
        raise ValueError("description must be between 1 and 256 characters")
    if name is not None and trimmed.lower() == name.strip().lower():
        raise ValueError("description must explain the permission, not repeat its name")
    return trimmed


def _generation(body: dict[str, Any], key: str, *, required: bool) -> int | None:
    value = body.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if required or value is not None:
        raise ApiUnavailableError(f"API response without {key}: permission")
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


def _permission(document: object) -> Permission:
    body = as_object(document, what="permission")
    desired = as_object(body.get("desired"), what="permission (desired)")
    spec_obj = desired.get("specification")
    spec = (
        as_object(cast(object, spec_obj), what="permission (specification)")
        if isinstance(spec_obj, dict)
        else desired
    )
    name = spec.get("name")
    if not isinstance(name, str):
        raise ApiUnavailableError("API response without the permission name")
    description = spec.get("description")
    if not isinstance(description, str):
        raise ApiUnavailableError("API response without the permission description")
    return Permission(
        resource_id=as_text(body, "resourceId", what="permission"),
        resource_version=as_text(body, "resourceVersion", what="permission"),
        desired_generation=cast("int", _generation(body, "desiredGeneration", required=True)),
        observed_generation=_generation(body, "observedGeneration", required=False),
        phase=as_text(body, "phase", what="permission"),
        lifecycle=as_text(desired, "lifecycle", what="permission (desired)"),
        name=name,
        description=description,
        grantable=spec.get("grantable") is not False,
        deletion_protection=spec.get("deletionProtection") is True,
        status=as_text(spec, "status", what="permission (specification)")
        if "status" in spec
        else None,
        failure_reason=_failure_reason(body),
    )


def create_permission(
    api_url: str,
    *,
    token: str,
    name: str,
    description: str,
    grantable: bool = True,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> Permission:
    """Cria uma permissão atômica (requer ipm.permission.admin); a API a admite na hora."""
    valid_name = validate_permission_name(name)
    valid_desc = validate_description(description, name=valid_name)
    _, document = call_api(
        "POST",
        api_url,
        PERMISSIONS_PATH,
        token=token,
        body={
            "name": valid_name,
            "description": valid_desc,
            "grantable": grantable,
        },
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return _permission(document)


def update_permission(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    description: str | None = None,
    grantable: bool | None = None,
    protected: bool | None = None,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> Permission:
    """Altera descrição, grantable e/ou proteção contra exclusão."""
    resource_id = validate_identifier(resource_id, what="resourceId")
    body: dict[str, Any] = {"resourceVersion": resource_version}
    if description is not None:
        body["description"] = validate_description(description)
    if grantable is not None:
        body["grantable"] = grantable
    if protected is not None:
        body["deletionProtection"] = protected
    _, document = call_api(
        "PATCH",
        api_url,
        f"{PERMISSIONS_PATH}/{resource_id}",
        token=token,
        body=body,
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return _permission(document)


def set_permission_protection(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    protected: bool,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> Permission:
    return update_permission(
        api_url,
        token=token,
        resource_id=resource_id,
        resource_version=resource_version,
        protected=protected,
        idempotency_key=idempotency_key,
        allow_insecure_http=allow_insecure_http,
    )


def delete_permission(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> Permission:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "DELETE",
        api_url,
        f"{PERMISSIONS_PATH}/{resource_id}",
        token=token,
        query={"resourceVersion": resource_version},
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return _permission(document)


def get_permission(
    api_url: str, *, token: str, resource_id: str, allow_insecure_http: bool
) -> Permission:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "GET",
        api_url,
        f"{PERMISSIONS_PATH}/{resource_id}",
        token=token,
        allow_insecure_http=allow_insecure_http,
    )
    return _permission(document)


def list_permissions(api_url: str, *, token: str, allow_insecure_http: bool) -> list[Permission]:
    """Lista todas as permissões do catálogo, seguindo o cursor `after`."""
    found: list[Permission] = []
    after: str | None = None
    for _ in range(MAXIMUM_LIST_PAGES):
        query = {
            "limit": str(LIST_PAGE_SIZE),
            **({"after": after} if after else {}),
        }
        _, document = call_api(
            "GET",
            api_url,
            PERMISSIONS_PATH,
            token=token,
            query=query,
            allow_insecure_http=allow_insecure_http,
        )
        body = as_object(document, what="permissions list")
        items = body.get("items")
        if not isinstance(items, list):
            raise ApiUnavailableError("API response without an items list")
        found.extend(_permission(item) for item in cast("list[object]", items))
        after = body.get("nextCursor")
        if not isinstance(after, str) or not after:
            break
    return found
