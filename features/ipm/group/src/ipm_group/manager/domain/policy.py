"""Contrato da política de negócio do Grupo (ipm.group), sem I/O (decisões 0085 e 0088).

A política interpreta o `requested` do Grupo, calcula o novo `desired` e informa as regras de
unicidade e cotas. Quem consulta o estado do SSOT para aplicá-las é o adaptador `store/`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

Operation = Literal["create", "update", "delete"]


@dataclass(frozen=True, slots=True)
class Request:
    """Conteúdo de um `requested`, já validado, independente do tipo de recurso."""

    operation: Operation
    operation_id: str
    request_digest: str
    resource_version: int | None = None
    specification: Mapping[str, Any] | None = None
    reconciliation: str | None = None
    organization_quota_limit: int | None = None
    """Limite de grupos da Organization, definido pelo Receiver (ausente para o operador)."""


@dataclass(frozen=True, slots=True)
class UniqueValue:
    """Valor que não pode se repetir entre recursos ativos (`lifecycle = present`)."""

    field: str
    value: str
    lock_key: str
    """Chave que serializa as transações que disputam o mesmo valor."""

    scope_field: str | None = None
    scope_value: str | None = None
    """Campo e valor que delimitam a unicidade (ex.: `organizationId`)."""


@dataclass(frozen=True, slots=True)
class OwnerQuota:
    """Cota de recursos do tipo por dono (aqui, a Organization), conferida na mesma unidade atômica
    do pedido."""

    field: str
    owner: str
    limit: int
    lock_key: str
    """Chave que serializa as transações do mesmo dono."""


class ResourcePolicy(Protocol):
    def parse(self, operation: str, data: Mapping[str, Any]) -> Request: ...

    def desired_for_create(self, request: Request, requested_by: str) -> dict[str, Any]: ...

    def desired_for_update(
        self, current: Mapping[str, Any], request: Request
    ) -> dict[str, Any]: ...

    def desired_for_delete(self, current: Mapping[str, Any]) -> dict[str, Any]: ...

    def unique_value(self, desired: Mapping[str, Any]) -> UniqueValue | None:
        """Valor único que o `desired` ocupa, ou `None` quando não ocupa nenhum."""
        ...

    def invalid(self, desired: Mapping[str, Any]) -> bool:
        """Regra pura sobre o `desired` que o torna recusado."""
        ...

    def owner_quota(self, request: Request, desired: Mapping[str, Any]) -> OwnerQuota | None:
        """Cota de grupos por Organization, só no create e só com limite do Receiver."""
        ...

    def deletion_protected(self, current: Mapping[str, Any]) -> bool:
        """`True` enquanto o grupo está protegido contra exclusão (default `False`)."""
        ...

    def message_data(self, desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]: ...

    def is_converged(
        self, desired: Mapping[str, Any], presence: str, observed: Mapping[str, Any] | None
    ) -> bool:
        """Compara `desired` e `observed` pelos campos gerenciados."""
        ...
