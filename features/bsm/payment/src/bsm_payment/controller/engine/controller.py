"""Motor do Controller de Payment (`bsm.payment`, decisão 0096).

Executa a unificação do loop de reconciliação externa:
1. Informer consome o Stream DESIRED do NATS e enfileira na Workqueue.
2. Reavaliação periódica enfileira periodicamente os recursos da partição.
3. Workers processam itens da Workqueue chamando `reconcile(resource_id)`.
4. `reconcile`: lê SSOT sob lock, observa no gateway de pagamento, decide, executa se houver drift,
   reobserva e grava status e condições no SSOT.
"""

import asyncio
import hashlib
import logging
import random
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Protocol

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from bsm_payment.common.contracts.envelope import read_envelope
from bsm_payment.common.ids import new_identifier, utc_now
from bsm_payment.common.logging_config import bind_context, restore_context, save_context
from bsm_payment.common.resource import MODULE, RESOURCE_TYPE
from bsm_payment.controller.domain import convergence
from bsm_payment.controller.domain.decision import Decision, DesiredState, ObservedState, decide
from bsm_payment.controller.drivers.base import ProviderError
from bsm_payment.controller.drivers.registry import DriverRegistry
from bsm_payment.controller.engine import actions
from bsm_payment.controller.engine.actions import ActionFailedError
from bsm_payment.controller.engine.messages import Messages, subject_of
from bsm_payment.controller.engine.observation import ObservationResult, observe_payment
from bsm_payment.controller.engine.workqueue import Workqueue
from bsm_payment.controller.settings import LoopSettings, PartitionSettings
from bsm_payment.controller.store.ssot import ControllerSsotStore

logger = logging.getLogger(__name__)


class BillingAccounts(Protocol):
    def has_attached_billing_accounts(self, payment_id: str) -> bool: ...


def owns(resource_id: str, partition: PartitionSettings) -> bool:
    if partition.count <= 1:
        return True
    digest = int.from_bytes(hashlib.sha256(resource_id.encode("utf-8")).digest()[:8], "big")
    return digest % partition.count == partition.index


class PaymentController:
    def __init__(
        self,
        pool: AsyncConnectionPool[Any],
        drivers: DriverRegistry,
        *,
        billing_accounts: BillingAccounts | None = None,
        partition: PartitionSettings | None = None,
        loop_settings: LoopSettings | None = None,
        workqueue: Workqueue | None = None,
        clock: Callable[[], datetime] = utc_now,
        identifiers: Callable[[], str] = new_identifier,
    ) -> None:
        self._pool = pool
        self._drivers = drivers
        self._billing_accounts = billing_accounts
        self._partition = partition or PartitionSettings()
        self._loop = loop_settings or LoopSettings()
        self._workqueue = workqueue or Workqueue(clock=clock)
        self._clock = clock
        self._identifiers = identifiers
        self._messages = Messages(clock, identifiers)

    @property
    def workqueue(self) -> Workqueue:
        return self._workqueue

    async def on_message(self, data: bytes) -> bool:
        """Handler de mensagens do Stream DESIRED (Informer)."""
        envelope = read_envelope(data)
        if (
            envelope.message_type != "desired"
            or envelope.module != MODULE
            or envelope.resource_type != RESOURCE_TYPE
        ):
            return False

        if not owns(envelope.resource_id, self._partition):
            return True

        self._workqueue.add(envelope.resource_id)
        return True

    async def run_workers(self, stop: asyncio.Event) -> None:
        """Executa o pool de workers consumindo chaves da Workqueue."""
        workers = [
            asyncio.create_task(self._worker_loop(stop), name=f"controller-worker-{i}")
            for i in range(self._loop.workers)
        ]
        await stop.wait()
        self._workqueue.close()
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    async def _worker_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                resource_id = await self._workqueue.get()
            except asyncio.CancelledError:
                break
            try:
                retry = await self.reconcile(resource_id)
                if retry:
                    delay = self._workqueue.add_rate_limited(resource_id)
                    logger.info(
                        "resource requeued with backoff",
                        extra={
                            "smarkee.resource.id": resource_id,
                            "smarkee.reconcile.backoff_seconds": round(delay, 3),
                        },
                    )
                else:
                    self._workqueue.forget(resource_id)
            except Exception:
                logger.exception(
                    "unhandled error reconciling resource",
                    extra={"smarkee.resource.id": resource_id},
                )
                self._workqueue.add_rate_limited(resource_id)
            finally:
                self._workqueue.done(resource_id)

    async def run_periodic_resync(self, stop: asyncio.Event) -> None:
        """Enfileira periodicamente todos os recursos ativos do SSOT para detecção de drift."""
        await self._enqueue_all()
        while not stop.is_set():
            jitter = 1 + random.uniform(  # noqa: S311
                -self._loop.reevaluation_jitter, self._loop.reevaluation_jitter
            )
            delay = self._loop.reevaluation_interval_seconds * jitter
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
                break
            except TimeoutError:
                await self._enqueue_all()

    async def _enqueue_all(self) -> None:
        async with self._pool.connection() as conn:
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                "SELECT resource_id FROM bsm.payment"
                " WHERE reconciliation = 'active'"
                " ORDER BY resource_id"
            )
            rows = await cursor.fetchall()
        for row in rows:
            rid = str(row["resource_id"])
            if owns(rid, self._partition):
                self._workqueue.add(rid)

    async def reconcile(self, resource_id: str) -> bool:
        """Executa um ciclo completo de controle para `resource_id`.

        Retorna `True` se precisar ser reenfileirado com backoff (falha transitória).
        """
        if not owns(resource_id, self._partition):
            return False

        previous_ctx = save_context()
        try:
            bind_context(resource_id=resource_id)
            return await self._reconcile_in_context(resource_id)
        finally:
            restore_context(previous_ctx)

    async def _reconcile_in_context(self, resource_id: str) -> bool:
        snapshot = await self._load_snapshot(resource_id)
        if snapshot is None or snapshot["reconciliation"] == "suspended":
            return False

        desired: dict[str, Any] = snapshot["desired"]
        previous_observed = (
            snapshot["observed"] if isinstance(snapshot.get("observed"), dict) else None
        )
        bind_context(
            requested_by=snapshot.get("requested_by"),
            owner_id=desired.get("ownerAccountId"),
        )

        observation = await self._observe(
            resource_id,
            desired=desired,
            previous_observed=previous_observed,
        )
        if observation.presence == "unknown":
            await self._record_observation_only(resource_id, observation)
            return True

        decision = self._decide(desired, observation)
        if decision is None:
            await self._record_observation_only(resource_id, observation)
            return False

        if decision.operation == "delete" and self._has_attached_billing_accounts(resource_id):
            return await self._record_action_failure(
                resource_id,
                decision=decision,
                error=ActionFailedError(
                    "ResourcesAttached",
                    retryable=False,
                    message=(
                        "Payment method still has attached billing accounts;"
                        " replace or delete them first."
                    ),
                ),
            )

        action_result: dict[str, Any] | None = None
        try:
            action_result = await actions.execute(
                decision.operation,
                resource_id,
                desired,
                previous_observed=observation.data or previous_observed,
                drivers=self._drivers,
            )
        except ActionFailedError as error:
            return await self._record_action_failure(resource_id, decision=decision, error=error)

        reobservation = await self._observe(
            resource_id,
            desired=desired,
            previous_observed=action_result or observation.data or previous_observed,
        )
        await self._record_post_action(resource_id, decision=decision, observation=reobservation)
        return reobservation.presence == "unknown"

    def _has_attached_billing_accounts(self, resource_id: str) -> bool:
        if self._billing_accounts is None:
            return False
        return self._billing_accounts.has_attached_billing_accounts(resource_id)

    async def _load_snapshot(self, resource_id: str) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                "SELECT resource_id, resource_version, desired_generation, observed_generation,"
                " lifecycle, reconciliation, failure_count, phase, conditions, desired,"
                " observed, presence, requested_by, correlation_id"
                " FROM bsm.payment WHERE resource_id = %s",
                (resource_id,),
            )
            return await cursor.fetchone()

    async def _observe(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        previous_observed: Mapping[str, Any] | None,
    ) -> ObservationResult:
        try:
            return await observe_payment(
                resource_id,
                desired=desired,
                previous_observed=previous_observed,
                drivers=self._drivers,
            )
        except ProviderError as error:
            logger.warning(
                "payment gateway unavailable during observation",
                extra={
                    "smarkee.resource.id": resource_id,
                    "error.type": error.reason,
                },
            )
            return ObservationResult(presence="unknown", data={})

    def _decide(
        self, desired: Mapping[str, Any], observation: ObservationResult
    ) -> Decision | None:
        desired_state = DesiredState(
            lifecycle=str(desired.get("lifecycle", "present")),
            display_name=str(desired.get("displayName", "")),
            provider=str(desired.get("provider", "mercadopago")),
            method_type=str(desired.get("methodType", "credit_card")),
            deletion_protection=desired.get("deletionProtection", True) is not False,
        )
        observed_state = ObservedState(
            presence=observation.presence,
            display_name=observation.data.get("displayName"),
            provider=observation.data.get("provider"),
            method_type=observation.data.get("methodType"),
            status=observation.data.get("status"),
            deletion_protection=observation.data.get("deletionProtection"),
        )
        return decide(desired_state, observed_state)

    async def _record_observation_only(
        self, resource_id: str, observation: ObservationResult
    ) -> None:
        now = self._clock()
        async with ControllerSsotStore.transaction(self._pool) as store:
            row = await store.lock_resource(resource_id)
            if row is None:
                return
            generation = int(row["desired_generation"])
            decision = convergence.decide_observed(
                convergence.check_is_converged,
                desired=row["desired"],
                lifecycle=row["lifecycle"],
                generation=generation,
                observation_generation=generation,
                presence=observation.presence,
                observed=observation.data,
                previous_phase=row["phase"],
                previous_conditions=list(row["conditions"]),
                now=now,
                progress_deadline_seconds=self._loop.progress_deadline_seconds,
            )
            requested_by = str(row.get("requested_by") or "system")
            correlation_id = str(row.get("correlation_id") or self._identifiers())

            if decision.remove:
                await store.delete_resource(resource_id)
                updated_msg = self._messages.updated(
                    resource_id,
                    row,
                    requested_by=requested_by,
                    correlation_id=correlation_id,
                    removed=True,
                    observed_generation=generation,
                )
                await store.add_to_outbox(
                    updated_msg,
                    resource_id=resource_id,
                    subject=subject_of("updated", resource_id),
                )
                return

            expected_obs = (
                observation.data if observation.presence != "unknown" else row.get("observed")
            )
            changed = (
                row.get("presence") != observation.presence
                or row.get("observed") != expected_obs
                or row.get("phase") != decision.phase
                or row.get("conditions") != decision.conditions
                or (decision.converged and row.get("observed_generation") != generation)
            )
            if not changed:
                return

            updated = await store.save_observed(
                resource_id,
                observed=observation.data,
                presence=observation.presence,
                observed_at=now,
                phase=decision.phase,
                conditions=decision.conditions,
                converged=decision.converged,
                observation_generation=generation,
            )
            updated_msg = self._messages.updated(
                resource_id,
                updated,
                requested_by=requested_by,
                correlation_id=correlation_id,
            )
            await store.add_to_outbox(
                updated_msg,
                resource_id=resource_id,
                subject=subject_of("updated", resource_id),
            )

    async def _record_post_action(
        self,
        resource_id: str,
        *,
        decision: Decision,
        observation: ObservationResult,
    ) -> None:
        now = self._clock()
        async with ControllerSsotStore.transaction(self._pool) as store:
            row = await store.lock_resource(resource_id)
            if row is None:
                return
            generation = int(row["desired_generation"])
            requested_by = str(row.get("requested_by") or "system")
            correlation_id = str(row.get("correlation_id") or self._identifiers())

            obs_decision = convergence.decide_observed(
                convergence.check_is_converged,
                desired=row["desired"],
                lifecycle=row["lifecycle"],
                generation=generation,
                observation_generation=generation,
                presence=observation.presence,
                observed=observation.data,
                previous_phase=row["phase"],
                previous_conditions=list(row["conditions"]),
                now=now,
                progress_deadline_seconds=self._loop.progress_deadline_seconds,
            )

            logger.info(
                "controller action executed",
                extra={
                    "smarkee.resource.id": resource_id,
                    "smarkee.operation.name": decision.operation,
                    "smarkee.outcome": "succeeded",
                },
            )

            if obs_decision.remove:
                await store.delete_resource(resource_id)
                updated_msg = self._messages.updated(
                    resource_id,
                    row,
                    requested_by=requested_by,
                    correlation_id=correlation_id,
                    removed=True,
                    observed_generation=generation,
                )
                await store.add_to_outbox(
                    updated_msg,
                    resource_id=resource_id,
                    subject=subject_of("updated", resource_id),
                )
                return

            updated = await store.save_observed(
                resource_id,
                observed=observation.data,
                presence=observation.presence,
                observed_at=now,
                phase=obs_decision.phase,
                conditions=obs_decision.conditions,
                converged=obs_decision.converged,
                observation_generation=generation,
            )
            updated_msg = self._messages.updated(
                resource_id,
                updated,
                requested_by=requested_by,
                correlation_id=correlation_id,
            )
            await store.add_to_outbox(
                updated_msg,
                resource_id=resource_id,
                subject=subject_of("updated", resource_id),
            )

    async def _record_action_failure(
        self,
        resource_id: str,
        *,
        decision: Decision,
        error: ActionFailedError,
    ) -> bool:
        now = self._clock()
        async with ControllerSsotStore.transaction(self._pool) as store:
            row = await store.lock_resource(resource_id)
            if row is None:
                return False
            generation = int(row["desired_generation"])
            requested_by = str(row.get("requested_by") or "system")
            correlation_id = str(row.get("correlation_id") or self._identifiers())

            effective_limit = (
                self._loop.failure_limit if error.retryable else int(row["failure_count"]) + 1
            )
            result = convergence.decide_result(
                failed=True,
                failure_reason=error.reason,
                failure_limit=effective_limit,
                generation=generation,
                failure_count=int(row["failure_count"]),
                phase=str(row["phase"]),
                reconciliation=str(row["reconciliation"]),
                previous_conditions=list(row["conditions"]),
                now=now,
            )
            updated = await store.save_action_result(
                resource_id,
                failure_count=result.failure_count,
                phase=result.phase,
                reconciliation=result.reconciliation,
                conditions=result.conditions,
            )
            if result.suspend:
                desired_msg = self._messages.desired(
                    resource_id,
                    row["desired"],
                    result.reconciliation,
                    generation=generation,
                    requested_by=requested_by,
                    correlation_id=correlation_id,
                )
                await store.add_to_outbox(
                    desired_msg,
                    resource_id=resource_id,
                    subject=subject_of("desired", resource_id),
                )
            updated_msg = self._messages.updated(
                resource_id,
                updated,
                requested_by=requested_by,
                correlation_id=correlation_id,
            )
            await store.add_to_outbox(
                updated_msg,
                resource_id=resource_id,
                subject=subject_of("updated", resource_id),
            )
            logger.warning(
                "controller action failed",
                extra={
                    "smarkee.resource.id": resource_id,
                    "smarkee.operation.name": decision.operation,
                    "smarkee.outcome": "failed",
                    "error.type": error.reason,
                },
            )
            return error.retryable and not result.suspend
