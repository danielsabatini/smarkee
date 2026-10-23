"""Provisionamento automático da Billing Account inicial ("Free Tier") no cadastro (decisão 0082).

Quando `core.account` converge (`manager.updated.core.account.<accountId>.changed` com
`phase == "Ready"` e `lifecycle == "present"`), o Manager de `bsm.account` cria de forma idempotente
a Billing Account inicial do usuário (`displayName = "Free Tier"`, `billingCurrency = "BRL"`,
`billingContacts = [<email>]`, `deletionProtection = True`) no SSOT e no outbox.

O e-mail do usuário vem da última mensagem `manager.desired.core.account.<accountId>.changed` no
Stream `DESIRED`.
"""

import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any

from bsm_account.common.contracts import generated
from bsm_account.common.contracts.envelope import EnvelopeError, read_envelope
from bsm_account.common.ids import new_identifier, utc_now
from bsm_account.common.resource import SCHEMA_VERSION
from bsm_account.manager.domain.account import (
    free_tier_absent_desired,
    free_tier_desired,
    free_tier_operation_id,
    free_tier_remove_operation_id,
    free_tier_request_digest,
    free_tier_resource_id,
)
from bsm_account.manager.domain.errors import DuplicateWriteError, PermanentMessageError
from bsm_account.manager.domain.kind import ResourceKind
from bsm_account.manager.domain.outcome import Outcome, OutcomeKind
from bsm_account.manager.handlers.envelope import require
from bsm_account.manager.handlers.ports import Store
from bsm_account.manager.handlers.publishing import Publishing

logger = logging.getLogger(__name__)


def _parse_core_account_updated(raw_message: Mapping[str, Any]) -> generated.MessageEnvelope:
    try:
        envelope = read_envelope(raw_message)
    except EnvelopeError as error:
        raise PermanentMessageError(error.reason) from None
    if (
        envelope.message_type.value != "updated"
        or envelope.emitter.value != "manager"
        or envelope.module != "core"
        or envelope.resource_type != "account"
    ):
        raise PermanentMessageError("a mensagem não é um updated de manager para core.account")
    return envelope


class AccountUpdatedHandler:
    def __init__(
        self,
        email_of: Callable[[str], Awaitable[str | None]],
        *,
        clock: Callable[[], datetime] = utc_now,
        identifiers: Callable[[], str] = new_identifier,
    ) -> None:
        self._email_of = email_of
        self._clock = clock
        self._publishing = Publishing(clock, identifiers)

    async def handle(
        self, store: Store, kind: ResourceKind, raw_message: Mapping[str, Any]
    ) -> Outcome:
        envelope = _parse_core_account_updated(raw_message)
        if envelope.data.get("removed") is True:
            return await self._remove_free_tier(store, kind, envelope)
        if envelope.data.get("lifecycle") != "present" or envelope.data.get("phase") != "Ready":
            return Outcome(OutcomeKind.IGNORED)

        owner_id = envelope.resource_id
        operation_id = free_tier_operation_id(owner_id)
        resource_id = free_tier_resource_id(owner_id)
        email = await self._email_of(owner_id)
        if not email:
            logger.warning(
                "core.account email not found in DESIRED stream; skipping Free Tier creation",
                extra={"smarkee.owner.id": owner_id},
            )
            return Outcome(OutcomeKind.IGNORED)

        desired = free_tier_desired(owner_id, email)
        digest = free_tier_request_digest(email)
        try:
            async with store.transaction():
                if await store.recorded_digest(operation_id) is not None:
                    return Outcome(OutcomeKind.DUPLICATE)
                if await store.lock_for_request(resource_id) is not None:
                    return Outcome(OutcomeKind.DUPLICATE)
                unique = kind.policy.unique_value(desired)
                if unique is not None and await store.value_in_use(
                    unique, excluding_resource_id=resource_id
                ):
                    return Outcome(OutcomeKind.DUPLICATE)

                await store.insert_resource(
                    resource_id, schema_version=SCHEMA_VERSION, desired=desired
                )
                await store.insert_operation(
                    operation_id=operation_id,
                    resource_id=resource_id,
                    operation_type="create",
                    generation=1,
                    requested_by=owner_id,
                    correlation_id=require(envelope.correlation_id),
                    request_digest=digest,
                    status="accepted",
                    reason=None,
                    completed_at=None,
                )
                cause = envelope.model_copy(
                    update={
                        "resource_id": resource_id,
                        "operation_id": operation_id,
                        "requested_by": owner_id,
                    }
                )
                await self._publishing.desired(
                    store,
                    kind,
                    cause,
                    desired=desired,
                    reconciliation="active",
                    generation=1,
                )
        except DuplicateWriteError:
            return Outcome(OutcomeKind.DUPLICATE)

        logger.info(
            "free tier billing account provisioned",
            extra={
                "smarkee.resource.id": resource_id,
                "smarkee.owner.id": owner_id,
                "smarkee.outcome": "accepted",
            },
        )
        return Outcome(OutcomeKind.ACCEPTED)

    async def _remove_free_tier(
        self,
        store: Store,
        kind: ResourceKind,
        envelope: generated.MessageEnvelope,
    ) -> Outcome:
        owner_id = envelope.resource_id
        resource_id = free_tier_resource_id(owner_id)
        operation_id = free_tier_remove_operation_id(owner_id)
        try:
            async with store.transaction():
                if await store.recorded_digest(operation_id) is not None:
                    return Outcome(OutcomeKind.DUPLICATE)
                row = await store.lock_for_request(resource_id)
                if row is None or row["lifecycle"] != "present":
                    return Outcome(OutcomeKind.IGNORED)
                desired = free_tier_absent_desired(row["desired"])
                generation = await store.change_desired(
                    resource_id,
                    desired=desired,
                    reconciliation="active",
                    phase="Deleting",
                    expected_resource_version=row["resource_version"],
                )
                if generation is None:
                    return Outcome(OutcomeKind.IGNORED)
                await store.insert_operation(
                    operation_id=operation_id,
                    resource_id=resource_id,
                    operation_type="delete",
                    generation=generation,
                    requested_by=owner_id,
                    correlation_id=require(envelope.correlation_id),
                    request_digest="0" * 64,
                    status="accepted",
                    reason=None,
                    completed_at=None,
                )
                cause = envelope.model_copy(
                    update={
                        "resource_id": resource_id,
                        "operation_id": operation_id,
                        "requested_by": owner_id,
                    }
                )
                await self._publishing.desired(
                    store,
                    kind,
                    cause,
                    desired=desired,
                    reconciliation="active",
                    generation=generation,
                )
        except DuplicateWriteError:
            return Outcome(OutcomeKind.DUPLICATE)

        logger.info(
            "free tier billing account removal scheduled after core.account removal",
            extra={
                "smarkee.resource.id": resource_id,
                "smarkee.owner.id": owner_id,
                "smarkee.outcome": "accepted",
            },
        )
        return Outcome(OutcomeKind.ACCEPTED)
