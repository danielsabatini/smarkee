"""Cliente do `sum.service` na API da plataforma (`docs/RESOURCE-CONTROL-LOOP.md`, §6.1).

Ligar e desligar são escritas assíncronas: a API responde `202` com o `operationId`, e o estado
definitivo vem da ligação (`phase`) e da Operation (`operationStatus`). Os dados chegam pelo mesmo
`api.call_api`, com o token da sessão.
"""

from dataclasses import dataclass
from typing import cast

from sk.features.api_contract import (
    OPAQUE_IDENTIFIER_PATTERN,
    OperationStatus,
    RequestAccepted,
    as_object,
    as_text,
    parse_accepted,
    parse_operation,
    validate_identifier,
)
from sk.http import ApiUnavailableError, call_api

__all__ = [
    "OPAQUE_IDENTIFIER_PATTERN",
    "OperationStatus",
    "ServiceLink",
    "ServiceRequestAccepted",
    "validate_identifier",
]

SERVICES_PATH = "/v1/sum/services"
ServiceRequestAccepted = RequestAccepted


@dataclass(frozen=True, slots=True)
class ServiceLink:
    """Uma ligação de serviço do solicitante, como a API a devolve."""

    resource_id: str
    resource_version: str
    phase: str
    service: str
    lifecycle: str
    observed_permissions: tuple[str, ...]


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
        phase=as_text(body, "phase", what="service"),
        service=as_text(desired, "service", what="service (desired)"),
        lifecycle=as_text(desired, "lifecycle", what="service (desired)"),
        observed_permissions=tuple(
            str(permission) for permission in cast("list[object]", permissions)
        ),
    )


def enable_service(
    api_url: str,
    *,
    token: str,
    service: str,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> ServiceRequestAccepted:
    _, document = call_api(
        "POST",
        api_url,
        SERVICES_PATH,
        token=token,
        body={"service": service},
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return parse_accepted(document)


def disable_service(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    allow_insecure_http: bool,
) -> ServiceRequestAccepted:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "DELETE",
        api_url,
        f"{SERVICES_PATH}/{resource_id}",
        token=token,
        query={"resourceVersion": resource_version},
        allow_insecure_http=allow_insecure_http,
    )
    return parse_accepted(document)


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
        f"{SERVICES_PATH}/{resource_id}/operations/{operation_id}",
        token=token,
        allow_insecure_http=allow_insecure_http,
    )
    return parse_operation(document)
