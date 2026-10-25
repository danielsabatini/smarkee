"""Contrato da política de negócio de um tipo de recurso, sem I/O.

A política interpreta o `requested` do seu tipo, calcula o novo `desired` e informa as regras de
unicidade. Quem consulta o estado do SSOT para aplicá-las é o adaptador `store/` (decisão 0017).
O `desired` guardado no SSOT tem o formato do contrato (camelCase) e contém a especificação **e**
o `lifecycle`; a `reconciliation` é um campo à parte, porque mudá-la não incrementa a geração
(`docs/SCHEMA.md` §7.1).
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


@dataclass(frozen=True, slots=True)
class UniqueValue:
    """Valor que não pode se repetir entre recursos ativos (`lifecycle = present`)."""

    field: str
    value: str
    lock_key: str
    """Chave que serializa as transações que disputam o mesmo valor."""


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

    def deletion_protected(self, current: Mapping[str, Any]) -> bool:
        """`True` enquanto o recurso está protegido contra exclusão (campo ausente vale `True`)."""
        ...

    def message_data(self, desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]: ...

    def is_converged(
        self, desired: Mapping[str, Any], presence: str, observed: Mapping[str, Any] | None
    ) -> bool:
        """Compara `desired` e `observed` pelos campos gerenciados (`docs/SCHEMA.md` §9.1)."""
        ...
