"""Admissão síncrona de uma escrita (decisão 0098): regras, recurso e `desired` numa transação.

Substitui o `requested` e o Manager: a requisição só termina depois que o recurso e o `desired`
(no outbox) foram gravados atomicamente. Quem publica o `desired` é o Publisher. Aqui só há
orquestração; a política é de `domain/` e a gravação é de `store/` (via `ports`).
"""

import logging
from http import HTTPStatus
from typing import Any

from ipm_serviceaccount.api.domain.admission import Admission, desired_message, desired_subject
from ipm_serviceaccount.api.domain.errors import ApiError, conflict, not_found
from ipm_serviceaccount.api.domain.records import ResourceRecord
from ipm_serviceaccount.api.domain.serviceaccount import (
    deletion_protected,
    desired_for_create,
    desired_for_delete,
    desired_for_update,
    message_data,
    owner_quota,
    unique_value,
)
from ipm_serviceaccount.api.http.ports import AdmissionStore, AdmissionTransaction
from ipm_serviceaccount.common.resource import SCHEMA_VERSION

logger = logging.getLogger(__name__)


async def admit(store: AdmissionStore, admission: Admission) -> ResourceRecord:
    """Aplica a escrita e devolve o recurso como ficou (ou o já aplicado, se for repetição)."""
    async with store.transaction() as transaction:
        replay = await _replay(transaction, admission)
        if replay is not None:
            return replay
        if admission.operation == "create":
            resource_id = await _create(transaction, admission)
        else:
            resource_id = await _change(transaction, admission)
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


async def _create(transaction: AdmissionTransaction, admission: Admission) -> str:
    specification = _required_specification(admission)
    desired = desired_for_create(specification)
    await _check_rules(transaction, admission, desired, quota_limit=admission.quota_limit)
    await transaction.insert_resource(
        admission.resource_id,
        schema_version=SCHEMA_VERSION,
        desired=desired,
        requested_by=admission.requested_by,
        correlation_id=admission.correlation_id,
    )
    await _publish(transaction, admission, desired, reconciliation="active", generation=1)
    return admission.resource_id


async def _change(transaction: AdmissionTransaction, admission: Admission) -> str:
    row = await transaction.lock_resource(admission.resource_id)
    if row is None:
        raise not_found()
    if row["resource_version"] != admission.resource_version:
        raise conflict()

    current: dict[str, Any] = row["desired"]
    if admission.operation == "delete":
        if deletion_protected(current):
            raise ApiError(
                HTTPStatus.CONFLICT,
                "DeletionProtected",
                "A service account está protegida contra exclusão. Desproteja-a antes de excluir.",
            )
        desired = desired_for_delete(current)
    else:
        if row["lifecycle"] != "present":
            raise ApiError(
                HTTPStatus.CONFLICT,
                "NotPresent",
                "A service account está em exclusão e não aceita alterações.",
            )
        desired = desired_for_update(current, admission.specification or {})
        await _check_rules(transaction, admission, desired, quota_limit=None)

    changed = desired != current
    # Nova geração volta a reconciliar, salvo declaração em contrário (docs/data/SSOT.md §10.4).
    reconciliation = admission.reconciliation or (
        "active" if changed else str(row["reconciliation"])
    )
    if not changed and reconciliation == row["reconciliation"]:
        return admission.resource_id  # nada a gravar nem a publicar: devolve o recurso atual

    phase = str(row["phase"])
    if changed:
        phase = "Deleting" if desired["lifecycle"] == "absent" else "Reconciling"
    generation = await transaction.change_desired(
        admission.resource_id,
        desired=desired,
        reconciliation=reconciliation,
        phase=phase,
        expected_resource_version=int(row["resource_version"]),
        requested_by=admission.requested_by,
        correlation_id=admission.correlation_id,
    )
    if generation is None:  # defensivo: a linha está bloqueada e a versão foi conferida
        raise conflict()
    await _publish(
        transaction, admission, desired, reconciliation=reconciliation, generation=generation
    )
    return admission.resource_id


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
            "Já existe uma service account com este nome na Organization.",
            field="name",
        )
    quota = owner_quota(desired, quota_limit)
    if quota is not None and await transaction.owned_count(quota) >= quota.limit:
        raise ApiError(
            HTTPStatus.FORBIDDEN,
            "QuotaExceeded",
            "Limite de service accounts da Organization atingido.",
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


def _required_specification(admission: Admission) -> dict[str, Any]:
    if admission.specification is None:
        raise ApiError(HTTPStatus.BAD_REQUEST, "ValidationFailed", "Especificação ausente.")
    return dict(admission.specification)
