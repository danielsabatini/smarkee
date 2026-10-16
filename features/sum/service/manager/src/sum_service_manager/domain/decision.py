"""Decisão do Manager sobre um pedido de ligação ou desligamento (decisão 0033).

Puro: recebe o estado atual da ligação e devolve o que acontece. A gravação no SSOT e a publicação
do `desired` ficam fora daqui (handlers e store).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from sum_service_manager.domain.service import (
    ServiceNotAvailableError,
    disable_desired,
    enable_desired,
    roles_of,
)

RejectionReason = Literal["service_unavailable", "already_exists", "not_found", "conflict"]


@dataclass(frozen=True, slots=True)
class Accepted:
    """O pedido é aceito: o Manager grava este `desired` e publica a mudança."""

    desired: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Rejected:
    """O pedido é recusado de forma permanente. Nada é gravado (a Operation registra o motivo)."""

    reason: RejectionReason
    existing_resource_id: str | None = None
    """Só em `already_exists`: a ligação ativa que já existe, para o cliente saber qual é."""


Decision = Accepted | Rejected


@dataclass(frozen=True, slots=True)
class Link:
    """O que o Manager já sabe da ligação: o `resourceId`, a versão e o `desired` atual."""

    resource_id: str
    resource_version: str
    desired_generation: int
    desired: Mapping[str, Any]

    @property
    def is_active(self) -> bool:
        return self.desired["lifecycle"] == "present"


def decide_create(
    *,
    owner_account_id: str,
    service: str,
    catalog: Mapping[str, tuple[str, ...]],
    active_link: Link | None,
    existing_link: Link | None = None,
) -> Decision:
    """Ligar: o serviço está no catálogo e o par dono + serviço não tem ligação ativa.

    `existing_link` é a ligação que o `resourceId` do pedido já tem no SSOT, se tiver: o Receiver
    reaproveita o recurso do par quando ele foi desligado (o recurso é o par, e não cada ligar).
    Ela precisa ser do mesmo par e estar desligada; uma ligada é `already_exists`, e uma de outro
    par é `conflict`.
    """
    try:
        roles_of(catalog, service)
    except ServiceNotAvailableError:
        return Rejected("service_unavailable")
    if active_link is not None and active_link.is_active:
        return Rejected("already_exists", existing_resource_id=active_link.resource_id)
    if existing_link is not None:
        if (
            existing_link.desired.get("ownerAccountId") != owner_account_id
            or existing_link.desired.get("service") != service
        ):
            return Rejected("conflict")
        if existing_link.is_active:
            return Rejected("already_exists", existing_resource_id=existing_link.resource_id)
    return Accepted(enable_desired(owner_account_id, service, catalog))


def decide_delete(*, link: Link | None, expected_version: str) -> Decision:
    """Desligar: a ligação precisa existir e estar ativa, e a versão lida precisa ser a atual."""
    if link is None or not link.is_active:
        return Rejected("not_found")
    if link.resource_version != expected_version:
        return Rejected("conflict")
    return Accepted(disable_desired(link.desired))
