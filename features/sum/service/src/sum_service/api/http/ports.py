"""Portas que a camada HTTP exige dos adaptadores (`store/` e `transport/`, decisão 0017)."""

from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from sum_service.api.domain.attachments import Attachment
from sum_service.api.domain.records import ResourceRecord


class Repository(Protocol):
    async def get_service(self, resource_id: str) -> ResourceRecord | None: ...

    async def services_of(self, owner_account_id: str) -> list[ResourceRecord]:
        """Ligações do dono, ordenadas por `resource_id` (a ordem é determinística)."""
        ...


class Attachments(Protocol):
    """Projeção local dos recursos de outros módulos ligados a cada dono (decisão 0100)."""

    def of(self, service: str, owner_account_id: str) -> list[Attachment]:
        """Recursos do dono que dependem do serviço (vazio para serviço sem dependentes)."""
        ...

    def has_billing_account(self, owner_account_id: str) -> bool:
        """O dono tem ao menos uma Billing Account presente (decisão 0082)."""
        ...

    @property
    def is_synced(self) -> bool:
        """As projeções já leram o `DESIRED` inteiro: só então elas respondem."""
        ...


class AdmissionTransaction(Protocol):
    """Gravações da admissão dentro de uma única transação do SSOT (decisão 0098)."""

    async def lock_idempotency(self, requested_by: str, key: str) -> None: ...

    async def find_idempotency(self, requested_by: str, key: str) -> tuple[str, str] | None: ...

    async def record_idempotency(
        self, requested_by: str, key: str, *, request_digest: str, resource_id: str
    ) -> None: ...

    async def lock_pair(self, owner_account_id: str, service: str) -> dict[str, Any] | None:
        """Serializa o par dono + serviço e bloqueia o recurso dele: o ligado, ou o desligado
        mais recente."""
        ...

    async def insert_resource(
        self,
        resource_id: str,
        *,
        schema_version: str,
        desired: Mapping[str, Any],
        requested_by: str,
        correlation_id: str,
    ) -> None: ...

    async def lock_resource(self, resource_id: str) -> dict[str, Any] | None: ...

    async def change_desired(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        phase: str,
        expected_resource_version: int,
        requested_by: str,
        correlation_id: str,
    ) -> int | None: ...

    async def add_to_outbox(
        self, message: Mapping[str, Any], *, resource_id: str, subject: str
    ) -> None: ...

    async def fetch_record(self, resource_id: str) -> ResourceRecord | None: ...


class AdmissionStore(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[AdmissionTransaction]: ...
