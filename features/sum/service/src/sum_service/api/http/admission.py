"""Admissão síncrona de uma escrita (decisão 0098): regras, recurso e `desired` numa transação.

Substitui o `requested` e o Manager: a requisição só termina depois que o recurso e o `desired`
(no outbox) foram gravados atomicamente. Quem publica o `desired` é o Publisher. Aqui só há
orquestração; a política é de `domain/` e a gravação é de `store/` (via `ports`).

O recurso é o par dono + serviço (decisão 0033): ligar de novo um par desligado reaproveita o
recurso dele, com uma geração nova; o par ligado é `409`.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from http import HTTPStatus
from typing import Any

from sum_service.api.domain.admission import Admission, desired_message, desired_subject
from sum_service.api.domain.errors import ApiError, conflict, not_found
from sum_service.api.domain.records import ResourceRecord
from sum_service.api.domain.service import message_data
from sum_service.api.http.ports import AdmissionStore, AdmissionTransaction
from sum_service.common.resource import SCHEMA_VERSION
from sum_service.common.service_rules import (
    ServiceNotAvailableError,
    disable_desired,
    enable_desired,
)

logger = logging.getLogger(__name__)

ALREADY_ENABLED = "AlreadyEnabled"
SERVICE_NOT_AVAILABLE = "ServiceNotAvailable"


@dataclass(frozen=True, slots=True)
class Rules:
    """Catálogo de serviços e pré-condições que dependem de outros módulos (decisões 0040, 0082)."""

    catalog: Mapping[str, tuple[str, ...]]
    before_enable: Callable[[str], None]
    """Levanta `ApiError` se o dono não pode habilitar um serviço (sem Billing Account)."""

    before_disable: Callable[[str, str], None]
    """Levanta `ApiError` se algo do dono depende do serviço."""


async def admit(store: AdmissionStore, admission: Admission, rules: Rules) -> ResourceRecord:
    """Aplica a escrita e devolve o recurso como ficou (ou o já aplicado, se for repetição)."""
    async with store.transaction() as transaction:
        replay = await _replay(transaction, admission)
        if replay is not None:
            return replay
        if admission.operation == "create":
            resource_id = await _create(transaction, admission, rules)
        else:
            resource_id = await _delete(transaction, admission, rules)
        if admission.idempotency_key is not None:
            await transaction.record_idempotency(
                admission.requested_by,
                admission.idempotency_key,
                request_digest=admission.request_digest,
                resource_id=resource_id,
            )
        record = await transaction.fetch_record(resource_id)
    if record is None:  # defensivo: a linha acabou de ser gravada na mesma transação
        raise not_found()
    logger.info(
        "write admitted",
        extra={
            "smarkee.resource.id": resource_id,
            "smarkee.operation.name": admission.operation,
            "smarkee.outcome": "accepted",
        },
    )
    return record


async def _replay(transaction: AdmissionTransaction, admission: Admission) -> ResourceRecord | None:
    """Repetição do cliente com a mesma `Idempotency-Key`: devolve o recurso atual, sem gravar."""
    key = admission.idempotency_key
    if key is None:
        return None
    await transaction.lock_idempotency(admission.requested_by, key)
    found = await transaction.find_idempotency(admission.requested_by, key)
    if found is None:
        return None
    digest, resource_id = found
    if digest != admission.request_digest:
        raise ApiError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "IdempotencyKeyReused",
            "A Idempotency-Key já foi usada com outro conteúdo.",
            field="Idempotency-Key",
        )
    record = await transaction.fetch_record(resource_id)
    if record is None:
        raise not_found()
    return record


async def _create(transaction: AdmissionTransaction, admission: Admission, rules: Rules) -> str:
    service = admission.service
    if service is None:  # defensivo: o HTTP sempre informa o serviço no create
        raise ApiError(HTTPStatus.BAD_REQUEST, "ValidationFailed", "Serviço ausente.")
    owner = admission.requested_by
    existing = await transaction.lock_pair(owner, service)
    if existing is not None and existing["lifecycle"] == "present":
        raise ApiError(
            HTTPStatus.CONFLICT,
            ALREADY_ENABLED,
            f"O serviço {service} já está habilitado (resourceId {existing['resource_id']}).",
        )
    rules.before_enable(owner)
    try:
        desired = enable_desired(
            owner, service, rules.catalog, existing["desired"] if existing else None
        )
    except ServiceNotAvailableError:
        raise ApiError(
            HTTPStatus.CONFLICT,
            SERVICE_NOT_AVAILABLE,
            f"O serviço {service} não está disponível.",
            field="service",
        ) from None
    if existing is None:
        await transaction.insert_resource(
            admission.resource_id,
            schema_version=SCHEMA_VERSION,
            desired=desired,
            requested_by=admission.requested_by,
            correlation_id=admission.correlation_id,
        )
        await _publish(transaction, admission, admission.resource_id, desired, generation=1)
        return admission.resource_id
    # Religar reaproveita o recurso do par: novo `desired` e geração seguinte.
    resource_id = str(existing["resource_id"])
    generation = await transaction.change_desired(
        resource_id,
        desired=desired,
        phase="Reconciling",
        expected_resource_version=int(existing["resource_version"]),
        requested_by=admission.requested_by,
        correlation_id=admission.correlation_id,
    )
    if generation is None:  # defensivo: a linha está bloqueada e a versão foi conferida
        raise conflict()
    await _publish(transaction, admission, resource_id, desired, generation=generation)
    return resource_id


async def _delete(transaction: AdmissionTransaction, admission: Admission, rules: Rules) -> str:
    row = await transaction.lock_resource(admission.resource_id)
    current: dict[str, Any] | None = None if row is None else row["desired"]
    # De outro dono é `404`, para não revelar que a ligação existe.
    if row is None or current is None or current["ownerAccountId"] != admission.requested_by:
        raise not_found()
    if row["resource_version"] != admission.resource_version:
        raise conflict()
    if row["lifecycle"] == "absent":
        return admission.resource_id  # repetir o DELETE de uma ligação desfeita não muda nada
    rules.before_disable(admission.requested_by, str(current["service"]))
    desired = disable_desired(current, rules.catalog)
    generation = await transaction.change_desired(
        admission.resource_id,
        desired=desired,
        phase="Deleting",
        expected_resource_version=int(row["resource_version"]),
        requested_by=admission.requested_by,
        correlation_id=admission.correlation_id,
    )
    if generation is None:  # defensivo: a linha está bloqueada e a versão foi conferida
        raise conflict()
    await _publish(transaction, admission, admission.resource_id, desired, generation=generation)
    return admission.resource_id


async def _publish(
    transaction: AdmissionTransaction,
    admission: Admission,
    resource_id: str,
    desired: dict[str, Any],
    *,
    generation: int,
) -> None:
    message = desired_message(
        replace(admission, resource_id=resource_id),
        generation=generation,
        data=message_data(desired),
    )
    await transaction.add_to_outbox(
        message, resource_id=resource_id, subject=desired_subject(resource_id)
    )
