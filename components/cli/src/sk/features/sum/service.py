"""Cliente do `sum.service` na API da plataforma (`docs/RESOURCE-CONTROL-LOOP.md`, §6.1).

Ligar e desligar são escritas assíncronas: a API responde `202` com o `operationId`, e o estado
definitivo vem da ligação (`phase`) e da Operation (`operationStatus`). Os dados chegam pelo mesmo
`api.call_api`, com o token da sessão.
"""

import re
from dataclasses import dataclass
from typing import Any, cast

from sk.http import ApiUnavailableError, call_api

SERVICES_PATH = "/v1/sum/services"
# `resourceId` e `operationId` são identificadores opacos: o mesmo padrão de
# `schemas/common/definitions.v1.schema.json` (`resourceId` e `opaqueIdentifier`).
OPAQUE_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")


@dataclass(frozen=True, slots=True)
class ServiceRequestAccepted:
    """`202`: a identidade do pedido, para acompanhar a Operation."""

    resource_id: str
    operation_id: str


@dataclass(frozen=True, slots=True)
class ServiceLink:
    """Uma ligação de serviço do solicitante, como a API a devolve."""

    resource_id: str
    resource_version: str
    phase: str
    service: str
    lifecycle: str
    observed_roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OperationStatus:
    """Estado de uma Operation. `reason` só existe quando o pedido foi recusado."""

    operation_id: str
    operation_status: str
    reason: str | None


def validate_identifier(value: str, *, what: str) -> str:
    """Devolve o identificador se ele segue o contrato, ou levanta `ValueError`.

    Os identificadores entram no caminho da URL: aceitar texto livre permitiria `../`, `?` e `#`
    levarem o token da sessão a outro caminho da API. O padrão do contrato só admite letras
    minúsculas, números e hífen, caracteres que não alteram o caminho. A mensagem não repete o
    valor informado.
    """
    if not OPAQUE_IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(
            f"{what} inválido: use letras minúsculas, números e hífen (até 128 caracteres)"
        )
    return value


def _object(document: object, *, what: str) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ApiUnavailableError(f"resposta da API fora do contrato: {what}")
    return cast(dict[str, Any], document)


def _text(document: dict[str, Any], key: str, *, what: str) -> str:
    value = document.get(key)
    if not isinstance(value, str):
        raise ApiUnavailableError(f"resposta da API sem {key}: {what}")
    return value


def _accepted(document: object) -> ServiceRequestAccepted:
    body = _object(document, what="aceite")
    return ServiceRequestAccepted(
        resource_id=_text(body, "resourceId", what="aceite"),
        operation_id=_text(body, "operationId", what="aceite"),
    )


def _link(document: object) -> ServiceLink:
    body = _object(document, what="ligação")
    desired = _object(body.get("desired"), what="ligação (desired)")
    observed: object = body.get("observed") or {}
    roles: object = _object(observed, what="ligação (observed)").get("serviceRoles") or []
    if not isinstance(roles, list):
        raise ApiUnavailableError("resposta da API com serviceRoles inválido")
    return ServiceLink(
        resource_id=_text(body, "resourceId", what="ligação"),
        resource_version=_text(body, "resourceVersion", what="ligação"),
        phase=_text(body, "phase", what="ligação"),
        service=_text(desired, "service", what="ligação (desired)"),
        lifecycle=_text(desired, "lifecycle", what="ligação (desired)"),
        observed_roles=tuple(str(role) for role in cast("list[object]", roles)),
    )


def _operation(document: object) -> OperationStatus:
    body = _object(document, what="operação")
    reason = body.get("operationStatusReason")
    return OperationStatus(
        operation_id=_text(body, "operationId", what="operação"),
        operation_status=_text(body, "operationStatus", what="operação"),
        reason=reason if isinstance(reason, str) else None,
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
    return _accepted(document)


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
    return _accepted(document)


def list_services(api_url: str, *, token: str, allow_insecure_http: bool) -> list[ServiceLink]:
    _, document = call_api(
        "GET", api_url, SERVICES_PATH, token=token, allow_insecure_http=allow_insecure_http
    )
    items = _object(document, what="listagem").get("items")
    if not isinstance(items, list):
        raise ApiUnavailableError("resposta da API sem items")
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
    return _operation(document)
