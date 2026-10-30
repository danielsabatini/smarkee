"""Admissão síncrona de uma escrita (decisão 0098): regras, recurso e `desired` numa transação.

Substitui o `requested` e o Manager: a requisição só termina depois que o recurso e o `desired`
(no outbox) foram gravados atomicamente. Quem publica o `desired` é o Publisher. Aqui só há
orquestração; a política é de `domain/` e a gravação é de `store/` (via `ports`).
"""

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Any, cast

from core_account.api.domain.account import (
    REGISTRATION_TICKET_TTL_SECONDS,
    RESEND_MIN_INTERVAL_SECONDS,
    deletion_protected,
    desired_for_create,
    desired_for_delete,
    desired_for_update,
    mask_email,
    message_data,
    unique_value,
)
from core_account.api.domain.admission import Admission, desired_message, desired_subject
from core_account.api.domain.errors import ApiError, conflict, not_found
from core_account.api.domain.records import ResourceRecord
from core_account.api.http.ports import AdmissionStore, AdmissionTransaction, Repository
from core_account.common.contracts import generated
from core_account.common.ids import new_identifier
from core_account.common.resource import SCHEMA_VERSION

logger = logging.getLogger(__name__)

NAME_IN_USE = "NameInUse"


async def register(
    store: AdmissionStore,
    admission: Admission,
    *,
    identifiers: Callable[[], str],
    clock: Callable[[], datetime],
) -> dict[str, Any]:
    """Auto-cadastro anônimo com emissão de ticket temporário de rastreamento (UUIDv7).

    Idempotente: se a conta ainda não foi ativada, reemite o ticket e aciona o reenvio de
    ativação no Controller. Se a conta já existe e está ativada, retorna status uniforme
    sem vazar detalhes nem permitir enumeração.
    """
    now = clock()
    expires_at = now + timedelta(seconds=REGISTRATION_TICKET_TTL_SECONDS)
    ticket = identifiers()
    email = str(admission.specification["email"]) if admission.specification else ""

    async with store.transaction() as transaction:
        existing = await transaction.find_account_by_email(email)
        if existing is None:
            resource_id = await _create(transaction, admission)
            await transaction.create_registration_ticket(ticket, resource_id, email, expires_at)
            logger.info(
                "registration admitted",
                extra={
                    "smarkee.resource.id": resource_id,
                    "smarkee.operation.name": "create",
                    "smarkee.outcome": "accepted",
                },
            )
            return {
                "resourceId": resource_id,
                "registrationTicket": ticket,
                "ticketExpiresAt": expires_at,
            }

        is_activated = bool(
            existing.observed
            and (
                existing.observed.get("emailVerified") is True
                or existing.observed.get("accountState") == "active"
            )
        )
        if is_activated:
            logger.info(
                "registration ignored for already active account",
                extra={"smarkee.outcome": "ignored", "error.type": NAME_IN_USE},
            )
            # Ticket e ID dummy para resposta uniforme sem vazar a conta existente
            return {
                "resourceId": admission.resource_id,
                "registrationTicket": ticket,
                "ticketExpiresAt": expires_at,
            }

        resource_id = existing.resource_id
        await transaction.create_registration_ticket(ticket, resource_id, email, expires_at)

        current = existing.desired
        desired = dict(current)
        desired["resendRequestedAt"] = now.isoformat()

        generation = await transaction.change_desired(
            resource_id,
            desired=desired,
            reconciliation="active",
            phase="Reconciling",
            expected_resource_version=existing.resource_version,
            requested_by=admission.requested_by,
            correlation_id=admission.correlation_id,
        )
        if generation is not None:
            await _publish(
                transaction,
                replace(admission, resource_id=resource_id, operation="update"),
                desired,
                reconciliation="active",
                generation=generation,
            )
        logger.info(
            "registration re-admitted with resend",
            extra={
                "smarkee.resource.id": resource_id,
                "smarkee.operation.name": "resend",
                "smarkee.outcome": "accepted",
            },
        )
        return {
            "resourceId": resource_id,
            "registrationTicket": ticket,
            "ticketExpiresAt": expires_at,
        }


async def get_registration_status(
    repository: Repository,
    ticket: str,
    *,
    clock: Callable[[], datetime],
) -> generated.AccountRegistrationStatus:
    """Consulta de status por ticket de rastreamento efêmero."""
    ticket_record = await repository.get_registration_ticket(ticket)
    now = clock()
    if ticket_record is None or ticket_record.expires_at < now:
        raise ApiError(
            HTTPStatus.NOT_FOUND,
            "TicketNotFound",
            "Ticket de cadastro não encontrado ou expirado.",
            field="ticket",
        )
    account = await repository.get_account(ticket_record.resource_id)
    if account is None:
        raise ApiError(
            HTTPStatus.NOT_FOUND,
            "TicketNotFound",
            "Ticket de cadastro não encontrado ou expirado.",
            field="ticket",
        )
    email_dispatched = bool(account.presence == "present")
    activated = bool(account.observed and account.observed.get("emailVerified") is True)
    return generated.AccountRegistrationStatus.model_validate(
        {
            "phase": account.phase,
            "emailMasked": mask_email(ticket_record.email),
            "emailDispatched": email_dispatched,
            "activated": activated,
            "ticketExpiresAt": ticket_record.expires_at,
        }
    )


async def resend_registration_activation(
    store: AdmissionStore,
    ticket: str,
    *,
    clock: Callable[[], datetime],
) -> None:
    """Solicita novo envio de e-mail de ativação via ticket válido e não expirado."""
    now = clock()
    async with store.transaction() as transaction:
        ticket_record = await transaction.get_registration_ticket(ticket)
        if ticket_record is None or ticket_record.expires_at < now:
            raise ApiError(
                HTTPStatus.NOT_FOUND,
                "TicketNotFound",
                "Ticket de cadastro não encontrado ou expirado.",
                field="ticket",
            )
        if ticket_record.last_resend_at is not None:
            elapsed = (now - ticket_record.last_resend_at).total_seconds()
            if elapsed < RESEND_MIN_INTERVAL_SECONDS:
                retry_after = int(RESEND_MIN_INTERVAL_SECONDS - elapsed) + 1
                raise ApiError(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    "RateLimited",
                    "Aguarde antes de solicitar um novo reenvio de ativação.",
                    headers={"Retry-After": str(retry_after)},
                )
        row = await transaction.lock_resource(ticket_record.resource_id)
        if row is None:
            raise ApiError(
                HTTPStatus.NOT_FOUND,
                "TicketNotFound",
                "Ticket de cadastro não encontrado ou expirado.",
                field="ticket",
            )
        raw_observed = row.get("observed")
        observed: dict[str, Any] = (
            cast(dict[str, Any], raw_observed) if isinstance(raw_observed, dict) else {}
        )
        if observed.get("emailVerified") is True:
            return

        current: dict[str, Any] = row["desired"]
        desired = dict(current)
        desired["resendRequestedAt"] = now.isoformat()
        generation = await transaction.change_desired(
            ticket_record.resource_id,
            desired=desired,
            reconciliation="active",
            phase="Reconciling",
            expected_resource_version=int(row["resource_version"]),
            requested_by="registration-ticket",
            correlation_id=ticket,
        )
        if generation is not None:
            admission = Admission(
                operation="update",
                resource_id=ticket_record.resource_id,
                requested_by="registration-ticket",
                correlation_id=ticket,
                request_digest=ticket,
                now=now,
                message_id=new_identifier(),
                specification=desired,
            )
            await _publish(
                transaction,
                admission,
                desired,
                reconciliation="active",
                generation=generation,
            )
        await transaction.update_ticket_resend(ticket, now)



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
    await _check_rules(transaction, admission, desired)
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
        # Repetir o DELETE de uma conta já em remoção não muda nada (idempotente).
        if current["lifecycle"] != "absent" and deletion_protected(current):
            raise ApiError(
                HTTPStatus.CONFLICT,
                "DeletionProtected",
                "A conta está protegida contra exclusão. Desproteja-a antes de excluir.",
            )
        desired = desired_for_delete(current)
    else:
        if row["lifecycle"] != "present":
            raise ApiError(
                HTTPStatus.CONFLICT,
                "NotPresent",
                "A conta está em exclusão e não aceita alterações.",
            )
        desired = desired_for_update(current, admission.specification or {})
        await _check_rules(transaction, admission, desired)

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
    transaction: AdmissionTransaction, admission: Admission, desired: dict[str, Any]
) -> None:
    """E-mail único entre as contas ativas, na mesma transação, com trava por chave."""
    unique = unique_value(desired)
    if unique is not None and await transaction.value_in_use(
        unique, excluding_resource_id=admission.resource_id
    ):
        raise ApiError(
            HTTPStatus.CONFLICT,
            NAME_IN_USE,
            "Já existe uma conta com este e-mail.",
            field="email",
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
