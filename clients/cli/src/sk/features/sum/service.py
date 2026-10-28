"""Cliente do `sum.service` na API da plataforma (`docs/loop/RESOURCE-CONTROL-LOOP.md`, §6.1).

Ligar e desligar são escritas síncronas (decisão 0098): a API admite o pedido e devolve a ligação
(`201` ao ligar, `202` ao desligar). A convergência se lê na própria ligação (`phase` e as gerações
desejada e observada). Os dados chegam pelo mesmo `api.call_api`, com o token da sessão.
"""

from dataclasses import dataclass
from typing import Any, cast

from sk.features.api_contract import (
    OPAQUE_IDENTIFIER_PATTERN,
    as_object,
    as_text,
    validate_identifier,
)
from sk.http import ApiUnavailableError, call_api

__all__ = ["OPAQUE_IDENTIFIER_PATTERN", "ServiceLink", "validate_identifier"]

SERVICES_PATH = "/v1/sum/services"


@dataclass(frozen=True, slots=True)
class ServiceLink:
    """Uma ligação de serviço do solicitante, como a API a devolve."""

    resource_id: str
    resource_version: str
    desired_generation: int
    observed_generation: int | None
    phase: str
    service: str
    lifecycle: str
    observed_permissions: tuple[str, ...]
    failure_reason: str | None = None


def _generation(body: dict[str, Any], key: str, *, required: bool) -> int | None:
    value = body.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if required or value is not None:
        raise ApiUnavailableError(f"API response without {key}: service")
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


def _link(document: object) -> ServiceLink:
    body = as_object(document, what="service")
    desired = as_object(body.get("desired"), what="service (desired)")
    observed: object = body.get("observed") or {}
    permissions: object = (
        as_object(observed, what="service (observed)").get("servicePermissions") or []
    )
    if not isinstance(permissions, list):
        raise ApiUnavailableError("API response with invalid servicePermissions")
    return ServiceLink(
        resource_id=as_text(body, "resourceId", what="service"),
        resource_version=as_text(body, "resourceVersion", what="service"),
        desired_generation=cast("int", _generation(body, "desiredGeneration", required=True)),
        observed_generation=_generation(body, "observedGeneration", required=False),
        phase=as_text(body, "phase", what="service"),
        service=as_text(desired, "service", what="service (desired)"),
        lifecycle=as_text(desired, "lifecycle", what="service (desired)"),
        observed_permissions=tuple(
            str(permission) for permission in cast("list[object]", permissions)
        ),
        failure_reason=_failure_reason(body),
    )


def enable_service(
    api_url: str,
    *,
    token: str,
    service: str,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> ServiceLink:
    _, document = call_api(
        "POST",
        api_url,
        SERVICES_PATH,
        token=token,
        body={"service": service},
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return _link(document)


def disable_service(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    allow_insecure_http: bool,
) -> ServiceLink:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "DELETE",
        api_url,
        f"{SERVICES_PATH}/{resource_id}",
        token=token,
        query={"resourceVersion": resource_version},
        allow_insecure_http=allow_insecure_http,
    )
    return _link(document)


def list_services(api_url: str, *, token: str, allow_insecure_http: bool) -> list[ServiceLink]:
    _, document = call_api(
        "GET", api_url, SERVICES_PATH, token=token, allow_insecure_http=allow_insecure_http
    )
    items = as_object(document, what="listing").get("items")
    if not isinstance(items, list):
        raise ApiUnavailableError("API response without items")
    return [_link(item) for item in cast("list[object]", items)]


def get_service(
    api_url: str, *, token: str, resource_id: str, allow_insecure_http: bool
) -> ServiceLink:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "GET",
        api_url,
        f"{SERVICES_PATH}/{resource_id}",
        token=token,
        allow_insecure_http=allow_insecure_http,
    )
    return _link(document)
