"""Portas que a camada HTTP exige dos adaptadores (`store/` e `transport/`, decisão 0017)."""

from typing import Protocol

from core_account.receiver.domain.attachments import Attachment
from core_account.receiver.domain.records import OperationRecord, ResourceRecord


class Repository(Protocol):
    async def get_account(self, resource_id: str) -> ResourceRecord | None: ...

    async def find_operation(self, operation_id: str) -> OperationRecord | None: ...


class AttachedResources(Protocol):
    async def of(self, access_token: str) -> list[Attachment]:
        """Recursos de outros módulos que pertencem ao dono do token (só os que existem).

        Consulta os módulos pelo fluxo normal, com o token do próprio solicitante.
        Levanta `AttachmentCheckError` se algum módulo não puder ser consultado.
        """
        ...
