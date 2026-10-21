"""Regras das ligações de serviço do SUM, comuns aos papéis (decisão 0033).

Usado pelo Manager (decide ligar e desligar), pelo Observer e pelo Executor (roles de cada serviço).
Puro: sem banco, rede ou relógio. O catálogo (serviço → roles) vem da configuração e é validado
aqui com os mesmos padrões dos contratos (`schemas/sum/service/definitions.v1.schema.json`).
"""

import json
import re
from collections.abc import Mapping
from typing import Any, cast

from pydantic import ValidationError

from sum_service.common.contracts import generated

SERVICE_PATTERN = re.compile(r"^[a-z][a-z0-9]*$")
ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9]*\.[a-z][a-z0-9]*\.[a-z][a-z0-9]*$")
MAX_ROLES_PER_SERVICE = 64

Catalog = dict[str, tuple[str, ...]]


class CatalogError(Exception):
    """Catálogo de serviços inválido: a configuração do componente está errada."""


class ServiceNotAvailableError(Exception):
    """O serviço não existe no catálogo. Recusa permanente do pedido (`Rejected`)."""

    def __init__(self, service: str) -> None:
        super().__init__(f"serviço {service!r} não existe no catálogo")
        self.service = service


def parse_catalog(raw: str) -> Catalog:
    """Lê o catálogo de `SUM_MANAGER_SERVICE_ROLES` (JSON: `{"ipm": ["ipm.organization.get"]}`).

    Erro explícito para cada problema, sem repetir valores além do necessário.
    """
    try:
        document: object = json.loads(raw)
    except json.JSONDecodeError:
        raise CatalogError("o catálogo de serviços não é JSON válido") from None
    if not isinstance(document, dict) or not document:
        raise CatalogError("o catálogo de serviços deve ser um objeto JSON com ao menos um serviço")
    catalog: Catalog = {}
    for service, roles in cast("dict[object, object]", document).items():
        if not isinstance(service, str) or not SERVICE_PATTERN.fullmatch(service):
            raise CatalogError("nome de serviço fora do padrão no catálogo")
        catalog[service] = _service_roles(service, roles)
    return catalog


def _service_roles(service: str, roles: object) -> tuple[str, ...]:
    if not isinstance(roles, list) or not roles:
        raise CatalogError(f"o serviço {service!r} precisa de ao menos uma role")
    names = cast("list[object]", roles)
    texts: list[str] = []
    for role in names:
        if not isinstance(role, str) or not ROLE_PATTERN.fullmatch(role):
            raise CatalogError(f"role fora do padrão <módulo>.<tipo>.<ação> em {service!r}")
        texts.append(role)
    if len(texts) > MAX_ROLES_PER_SERVICE or len(set(texts)) != len(texts):
        raise CatalogError(
            f"as roles de {service!r} devem ser únicas e até {MAX_ROLES_PER_SERVICE}"
        )
    return tuple(sorted(texts))


def roles_of(catalog: Mapping[str, tuple[str, ...]], service: str) -> tuple[str, ...]:
    """Roles do serviço no catálogo, ou `ServiceNotAvailableError` se ele não está nele."""
    roles = catalog.get(service)
    if roles is None:
        raise ServiceNotAvailableError(service)
    return roles


def managed_roles_of(current: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Roles que a ligação já controla (`managedRoles`, ou `serviceRoles` num `desired` antigo)."""
    if current is None:
        return ()
    roles: Any = current.get("managedRoles", current.get("serviceRoles", ()))
    return tuple(str(role) for role in cast("list[object]", roles or []))


def enable_desired(
    owner_account_id: str,
    service: str,
    catalog: Mapping[str, tuple[str, ...]],
    current: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """`desired` de uma ligação ativa: as roles do catálogo agora (decisão 0079).

    `managedRoles` soma as do catálogo às que a ligação já controlava: uma role que saiu do
    catálogo continua controlada, para ser revogada.
    """
    roles = roles_of(catalog, service)
    return _validated(
        {
            "lifecycle": "present",
            "reconciliation": "active",
            "ownerAccountId": owner_account_id,
            "service": service,
            "serviceRoles": list(roles),
            "managedRoles": sorted({*roles, *managed_roles_of(current)}),
        }
    )


def disable_desired(
    current: Mapping[str, Any], catalog: Mapping[str, tuple[str, ...]]
) -> dict[str, Any]:
    """`desired` de uma ligação desfeita: `absent`, sem roles, com o mesmo dono e serviço.

    A ligação continua existindo (decisão 0033): os recursos do usuário no serviço não são apagados.
    `managedRoles` diz o que revogar: as que a ligação controlava e as do catálogo agora.
    """
    service = str(current["service"])
    return _validated(
        {
            "lifecycle": "absent",
            "reconciliation": current["reconciliation"],
            "ownerAccountId": current["ownerAccountId"],
            "service": service,
            "serviceRoles": [],
            "managedRoles": sorted({*catalog.get(service, ()), *managed_roles_of(current)}),
        }
    )


def rollout_desired(
    current: Mapping[str, Any], catalog: Mapping[str, tuple[str, ...]]
) -> dict[str, Any] | None:
    """O `desired` da ligação com o catálogo de agora, ou `None` se nada muda (decisão 0079).

    Um serviço que saiu do catálogo não é alterado: a ligação fica como está, e quem decide o que
    fazer com ela é o operador.
    """
    service = str(current["service"])
    if service not in catalog:
        return None
    if current["lifecycle"] == "present":
        updated = enable_desired(str(current["ownerAccountId"]), service, catalog, current)
        updated["reconciliation"] = current["reconciliation"]
    else:
        updated = disable_desired(current, catalog)
    return None if updated == dict(current) else updated


def _validated(document: dict[str, Any]) -> dict[str, Any]:
    """Confere o documento com o contrato antes de devolvê-lo: nunca sai um `desired` inválido."""
    try:
        model = generated.ServiceDesiredData.model_validate(document)
    except ValidationError:
        raise ValueError("desired de sum.service fora do contrato") from None
    return model.model_dump(by_alias=True, mode="json")
