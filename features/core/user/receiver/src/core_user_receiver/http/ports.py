"""Portas que a camada HTTP exige dos adaptadores (`store/` e `transport/`, decisão 0017)."""

from typing import Protocol

from core_user_receiver.domain.attachments import Attachment
from core_user_receiver.domain.records import OperationRecord, ResourceRecord


class PublishError(Exception):
    """O transporte recusou ou não confirmou a publicação (indisponível, ou `REQUESTED` cheio).

    É uma rejeição repetível: o cliente pode tentar de novo (`docs/NATS.md` §6.3).
    """


class Publisher(Protocol):
    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        """Publica e aguarda a confirmação do transporte.

        `message_id` é a chave de deduplicação do transporte (`Nats-Msg-Id`).
        """
        ...


class Repository(Protocol):
    async def get_user(self, resource_id: str) -> ResourceRecord | None: ...

    async def find_operation(self, operation_id: str) -> OperationRecord | None: ...


class AttachedResources(Protocol):
    async def of(self, access_token: str) -> list[Attachment]:
        """Recursos de outros módulos que pertencem ao dono do token (só os que existem).

        Consulta os módulos pelo fluxo normal, com o token do próprio solicitante.
        Levanta `AttachmentCheckError` se algum módulo não puder ser consultado.
        """
        ...
