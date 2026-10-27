"""Admissão síncrona de uma escrita (decisão 0098): regras, recurso e `desired` numa transação.

Substitui o `requested` e o Manager: a requisição só termina depois que o recurso e o `desired`
(no outbox) foram gravados atomicamente. Quem publica o `desired` é o Publisher. Aqui só há
orquestração; a política é de `domain/` e a gravação é de `store/` (via `ports`).

O Grupo é só dado do SSOT (nenhum sistema externo o materializa): nasce e permanece `Ready` com
`observedGeneration` igual à geração, e a exclusão remove a linha e publica o `desired` com
`lifecycle = absent` (o tombstone que os consumidores do catálogo esperam).
"""

import logging
from http import HTTPStatus
from typing import Any

from ipm_group.api.domain.admission import Admission, desired_message, desired_subject
from ipm_group.api.domain.errors import ApiError, conflict, not_found
from ipm_group.api.domain.group import (
    deletion_protected,
    desired_for_create,
    desired_for_delete,
    desired_for_update,
    message_data,
    owner_quota,
    unique_value,
)
from ipm_group.api.domain.records import ResourceRecord
from ipm_group.api.http.ports import AdmissionStore, AdmissionTransaction
from ipm_group.common.resource import SCHEMA_VERSION

logger = logging.getLogger(__name__)


async def admit(store: AdmissionStore, admission: Admission) -> ResourceRecord:
    """Aplica a escrita e devolve o recurso como ficou (ou o já aplicado, se for repetição).

    No `delete`, devolve o recurso como era no momento da exclusão (`phase = Deleting`): a linha
    deixa de existir na mesma transação.
    """
    async with store.transaction() as transaction:
        replay = await _replay(transaction, admission)
        if replay is not None:
            return replay
        if admission.operation == "create":
            record = await _create(transaction, admission)
        elif admission.operation == "update":
            record = await _update(transaction, admission)
        else:
            record = await _delete(transaction, admission)
        if admission.idempotency_key is not None:
            await transaction.record_idempotency(
                admission.requested_by,
                admission.idempotency_key,
                request_digest=admission.request_digest,
                resource_id=admission.resource_id,
            )
    logger.info(
        "write admitted",
        extra={
            "smarkee.resource.id": admission.resource_id,
            "smarkee.operation.name": admission.operation,
            "smarkee.outcome": "accepted",
        },
    )
    return record


async def _replay(transaction: AdmissionTransaction, admission: Admission) -> ResourceRecord | None:
    """Repetição do cliente com a mesma `Idempotency-Key`: devolve o recurso atual, sem gravar.

    Depois de um `delete` aplicado o recurso não existe mais: a repetição recebe `404`, que para
    quem exclui significa que o Grupo já foi removido.
    """
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


async def _create(transaction: AdmissionTransaction, admission: Admission) -> ResourceRecord:
    if admission.specification is None:
        raise ValueError("specification is required for create")
    desired = desired_for_create(admission.specification)
    await _check_rules(transaction, admission, desired, quota_limit=admission.quota_limit)
    await transaction.insert_resource(
        admission.resource_id,
        schema_version=SCHEMA_VERSION,
        desired=desired,
        requested_by=admission.requested_by,
        correlation_id=admission.correlation_id,
    )
    await _publish(transaction, admission, desired, reconciliation="active", generation=1)
    return await _fetched(transaction, admission.resource_id)


async def _update(transaction: AdmissionTransaction, admission: Admission) -> ResourceRecord:
    row = await _locked(transaction, admission)
    current: dict[str, Any] = row["desired"]
    desired = desired_for_update(current, admission.specification or {})
    await _check_rules(transaction, admission, desired, quota_limit=None)

    changed = desired != current
    # Nova geração volta a reconciliar, salvo declaração em contrário (docs/data/SSOT.md §10.4).
    reconciliation = admission.reconciliation or (
        "active" if changed else str(row["reconciliation"])
    )
    if not changed and reconciliation == row["reconciliation"]:
        return await _fetched(transaction, admission.resource_id)  # nada a gravar nem a publicar

    generation = await transaction.change_desired(
        admission.resource_id,
        desired=desired,
        reconciliation=reconciliation,
        expected_resource_version=int(row["resource_version"]),
        requested_by=admission.requested_by,
        correlation_id=admission.correlation_id,
    )
    if generation is None:  # defensivo: a linha está bloqueada e a versão foi conferida
        raise conflict()
    await _publish(
        transaction, admission, desired, reconciliation=reconciliation, generation=generation
    )
    return await _fetched(transaction, admission.resource_id)


async def _delete(transaction: AdmissionTransaction, admission: Admission) -> ResourceRecord:
    row = await _locked(transaction, admission)
    current: dict[str, Any] = row["desired"]
    if deletion_protected(current):
        raise ApiError(
            HTTPStatus.CONFLICT,
            "DeletionProtected",
            "O grupo está protegido contra exclusão. Desproteja-o antes de excluir.",
        )
    record = await _fetched(transaction, admission.resource_id)
    desired = desired_for_delete(current)
    await _publish(
        transaction,
        admission,
        desired,
        reconciliation=str(row["reconciliation"]),
        generation=int(row["desired_generation"]) + 1,
    )
    await transaction.delete_resource(admission.resource_id)
    return _deleting(record, desired, generation=int(row["desired_generation"]) + 1)


def _deleting(
    record: ResourceRecord, desired: dict[str, Any], *, generation: int
) -> ResourceRecord:
    """O recurso como era, marcado como em exclusão, para a resposta do `DELETE`."""
    return ResourceRecord(
        resource_id=record.resource_id,
        resource_version=record.resource_version + 1,
        desired_generation=generation,
        observed_generation=record.observed_generation,
        lifecycle="absent",
        reconciliation=record.reconciliation,
        phase="Deleting",
        conditions=record.conditions,
        desired=desired,
        presence=record.presence,
        observed=record.observed,
        observed_at=record.observed_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


async def _locked(transaction: AdmissionTransaction, admission: Admission) -> dict[str, Any]:
    row = await transaction.lock_resource(admission.resource_id)
    if row is None:
        raise not_found()
    if row["resource_version"] != admission.resource_version:
        raise conflict()
    return row


async def _fetched(transaction: AdmissionTransaction, resource_id: str) -> ResourceRecord:
    record = await transaction.fetch_record(resource_id)
    if record is None:  # defensivo: a linha acabou de ser gravada na mesma transação
        raise not_found()
    return record


async def _check_rules(
    transaction: AdmissionTransaction,
    admission: Admission,
    desired: dict[str, Any],
    *,
    quota_limit: int | None,
) -> None:
    """Nome único e cota por Organization, na mesma transação, com trava por chave."""
    unique = unique_value(desired)
    if unique is not None and await transaction.value_in_use(
        unique, excluding_resource_id=admission.resource_id
    ):
        raise ApiError(
            HTTPStatus.CONFLICT,
            "NameInUse",
            "Já existe um grupo com este nome na Organization.",
            field="name",
        )
    quota = owner_quota(desired, quota_limit)
    if quota is not None and await transaction.owned_count(quota) >= quota.limit:
        raise ApiError(
            HTTPStatus.FORBIDDEN,
            "QuotaExceeded",
            "Limite de grupos da Organization atingido.",
        )


async def _publish(
    transaction: AdmissionTransaction,
    admission: Admission,
    desired: dict[str, Any],
    *,
    reconciliation: str,
    generation: int,
) -> None:
    message = desired_message(
        admission,
        desired=desired,
        reconciliation=reconciliation,
        generation=generation,
        data=message_data(desired, reconciliation),
    )
    await transaction.add_to_outbox(
        message, resource_id=admission.resource_id, subject=desired_subject(admission.resource_id)
    )
