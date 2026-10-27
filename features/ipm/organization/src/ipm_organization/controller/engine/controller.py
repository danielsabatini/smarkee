"""Motor do Controller da Organization (decisão 0096).

Executa a unificação do loop de reconciliação externa:
1. Informer consome o Stream DESIRED do NATS e enfileira na Workqueue.
2. Reavaliação periódica enfileira periodicamente os recursos da partição.
3. Workers processam itens da Workqueue chamando `reconcile(resource_id)`.
4. `reconcile`: lê SSOT sob lock, observa no Zitadel, decide, executa se houver drift,
   reobserva e grava status e condições no SSOT.
"""

import asyncio
import hashlib
import logging
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ipm_organization.common.contracts.envelope import read_envelope
from ipm_organization.common.dependents import DependentsProjection
from ipm_organization.common.ids import new_identifier, utc_now
from ipm_organization.common.logging_config import bind_context, restore_context, save_context
from ipm_organization.common.resource import MODULE, RESOURCE_TYPE
from ipm_organization.controller.domain.convergence import (
    ObservedDecision,
    check_is_converged,
    decide_observed,
    decide_result,
    set_condition,
)
from ipm_organization.controller.domain.decision import DesiredState, ObservedState, decide
from ipm_organization.controller.drivers.identity import ProviderError
from ipm_organization.controller.drivers.metadata import MetadataDriver
from ipm_organization.controller.drivers.organization import OrganizationDriver
from ipm_organization.controller.drivers.user_access import UserAccessDriver
from ipm_organization.controller.engine.actions import ActionFailedError, execute
from ipm_organization.controller.engine.messages import Messages, subject_of
from ipm_organization.controller.engine.observation import ObservationResult, observe_organization
from ipm_organization.controller.engine.workqueue import Workqueue
from ipm_organization.controller.settings import OrganizationControllerSettings
from ipm_organization.controller.store.ssot import ControllerSsotStore

logger = logging.getLogger(__name__)


def owns(resource_id: str, index: int, count: int) -> bool:
    """Partição determinística por resourceId."""
    digest = hashlib.sha256(resource_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % count == index


@dataclass(frozen=True, slots=True)
class ControllerDrivers:
    organizations: OrganizationDriver
    metadata: MetadataDriver
    user_access: UserAccessDriver


class OrganizationController:
    def __init__(
        self,
        pool: AsyncConnectionPool,
        drivers: ControllerDrivers,
        settings: OrganizationControllerSettings,
        *,
        dependents: DependentsProjection | None = None,
        clock: Callable[[], datetime] = utc_now,
        identifiers: Callable[[], str] = new_identifier,
    ) -> None:
        self._pool = pool
        self._drivers = drivers
        self._settings = settings
        self._dependents = dependents or DependentsProjection()
        self._clock = clock
        self._identifiers = identifiers
        self._workqueue = Workqueue()
        self._stop = asyncio.Event()

    @property
    def workqueue(self) -> Workqueue:
        return self._workqueue

    def owns_resource(self, resource_id: str) -> bool:
        return owns(
            resource_id,
            self._settings.partition.index,
            self._settings.partition.count,
        )

    # ------------------------------------------------------------------ Informer e Reavaliação

    async def on_message(self, data: bytes) -> object:
        """Processa mensagem recebida pelo StateConsumer."""
        return await self.on_desired_message(data)

    async def on_desired_message(self, data: bytes) -> str | None:
        """Chamado pelo Informer ao receber mensagem no stream DESIRED."""
        try:
            envelope = read_envelope(data)
        except Exception as err:
            logger.warning(
                "mensagem DESIRED inválida ignorada", extra={"error.type": type(err).__name__}
            )
            return None

        if envelope.module != MODULE or envelope.resource_type != RESOURCE_TYPE:
            return None

        resource_id = envelope.resource_id
        if self.owns_resource(resource_id):
            self._workqueue.add(resource_id)
            return resource_id
        return None

    async def run_periodic_reevaluation(self) -> None:
        """Enfileira periodicamente todos os recursos da partição para detectar drift externo."""
        interval = self._settings.loop.reevaluation_interval_seconds
        jitter_factor = self._settings.loop.reevaluation_jitter

        while not self._stop.is_set():
            jitter = 1 + random.uniform(-jitter_factor, jitter_factor)  # noqa: S311
            sleep_duration = max(1.0, interval * jitter)
            try:
                await asyncio.sleep(sleep_duration)
            except asyncio.CancelledError:
                break

            if self._stop.is_set():
                break

            try:
                await self._enqueue_all_owned()
            except Exception as err:
                logger.error(
                    "erro na reavaliação periódica", extra={"error.type": type(err).__name__}
                )

    async def _enqueue_all_owned(self) -> None:
        async with self._pool.connection() as conn:
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                "SELECT resource_id FROM ipm.organization WHERE reconciliation = 'active'"
            )
            rows = await cursor.fetchall()
            for row in rows:
                rid = str(row["resource_id"])
                if self.owns_resource(rid):
                    self._workqueue.add(rid)

    # ------------------------------------------------------------------ Worker

    async def run_worker(self, worker_id: int) -> None:
        """Executa um worker consumindo a Workqueue."""
        logger.info("iniciando worker do controller", extra={"smarkee.worker.index": worker_id})
        while not self._stop.is_set():
            try:
                resource_id = await self._workqueue.get()
            except asyncio.CancelledError:
                break

            try:
                saved = save_context()
                bind_context(resource_id=resource_id)
                try:
                    retry = await self.reconcile(resource_id)
                    if retry:
                        self._workqueue.add_rate_limited(resource_id)
                    else:
                        self._workqueue.forget(resource_id)
                finally:
                    restore_context(saved)
            except ProviderError as err:
                if err.retryable:
                    logger.warning(
                        "provedor indisponível na reconciliação, agendando retry com backoff",
                        extra={"error.type": type(err).__name__, "smarkee.reason": err.reason},
                    )
                    self._workqueue.add_rate_limited(resource_id)
                else:
                    logger.error(
                        "erro permanente no provedor na reconciliação",
                        extra={"error.type": type(err).__name__, "smarkee.reason": err.reason},
                    )
                    self._workqueue.forget(resource_id)
            except Exception as err:
                logger.exception(
                    "erro inesperado na reconciliação do recurso",
                    extra={"error.type": type(err).__name__},
                )
                self._workqueue.add_rate_limited(resource_id)
            finally:
                self._workqueue.done(resource_id)

    # ------------------------------------------------------------------ Reconciliação atômica

    async def reconcile(self, resource_id: str) -> bool:
        """Executa o ciclo atômico de reconciliação de uma Organization.

        Devolve se o recurso deve voltar à fila (com backoff): houve falha de ação ou ele ainda
        não convergiu e a reconciliação segue ativa. A observação, a ação, a reobservação, o
        estado, as Operations e o `updated` saem na mesma transação, com a linha bloqueada.
        """
        async with self._pool.connection() as conn:
            store = ControllerSsotStore(conn)
            async with store.transaction():
                row = await store.lock_resource(resource_id)
                if row is None or row["reconciliation"] == "suspended":
                    return False
                return await self._reconcile_locked(store, resource_id, row)

    async def _observe(self, resource_id: str) -> ObservationResult:
        return await observe_organization(
            resource_id,
            organizations=self._drivers.organizations,
            metadata=self._drivers.metadata,
            user_access=self._drivers.user_access,
        )

    async def _act(
        self, resource_id: str, desired: Mapping[str, Any], operation: str
    ) -> ActionFailedError | None:
        try:
            await execute(
                operation,
                resource_id,
                desired,
                organizations=self._drivers.organizations,
                metadata=self._drivers.metadata,
                user_access=self._drivers.user_access,
            )
        except ActionFailedError as err:
            return err
        except ProviderError as err:
            return ActionFailedError(err.reason, retryable=err.retryable, message=str(err))
        return None

    async def _reconcile_locked(
        self, store: ControllerSsotStore, resource_id: str, row: Mapping[str, Any]
    ) -> bool:
        desired: Mapping[str, Any] = row["desired"]
        generation: int = row["desired_generation"]
        lifecycle: str = row["lifecycle"]
        now = self._clock()

        observation = await self._observe(resource_id)
        has_dependents = self._dependents.has_dependents(resource_id)
        blocked_by_dependents = lifecycle == "absent" and has_dependents

        action = (
            None
            if blocked_by_dependents
            else decide(
                DesiredState(
                    lifecycle=lifecycle,
                    name=str(desired.get("name", "")),
                    platform_access=str(desired.get("platformAccess", "granted")),
                    deletion_protection=desired.get("deletionProtection", True) is not False,
                    user_access=desired.get("userAccess"),
                ),
                ObservedState(
                    presence=observation.presence,
                    name=observation.data.get("name"),
                    platform_access=observation.data.get("platformAccess"),
                    deletion_protection=observation.data.get("deletionProtection"),
                    user_access=observation.data.get("userAccess"),
                ),
            )
        )
        failure: ActionFailedError | None = None
        if action is not None:
            failure = await self._act(resource_id, desired, action.operation)
            observation = await self._observe(resource_id)  # reobserva logo após a ação

        # Limpa DeletionBlockedByDependents quando os dependentes já foram removidos
        row_conditions: list[dict[str, Any]] = row["conditions"] or []
        prev_conditions = [
            c for c in row_conditions if c.get("type") != "DeletionBlockedByDependents"
        ]

        # A observação é feita dentro do ciclo, depois da geração vigente: a confirma.
        if blocked_by_dependents:
            conditions = set_condition(
                prev_conditions,
                condition_type="DeletionBlockedByDependents",
                status="True",
                reason="DependentsRemaining",
                message=(
                    "A Organization possui recursos dependentes ativos."
                    " Remova-os antes de concluir a exclusão."
                ),
                generation=generation,
                now=now,
            )
            decision = ObservedDecision(
                phase="Deleting",
                conditions=conditions,
                converged=False,
                remove=False,
            )
        else:
            decision = decide_observed(
                check_is_converged,
                desired=desired,
                lifecycle=lifecycle,
                generation=generation,
                observation_generation=generation,
                presence=observation.presence,
                observed=observation.data,
                previous_phase=row["phase"],
                previous_conditions=prev_conditions,
                now=now,
                progress_deadline_seconds=self._settings.loop.progress_deadline_seconds,
            )
        self._log_deadlines(resource_id, generation, decision)
        messages = Messages(self._clock, self._identifiers)
        # Causa da geração vigente, gravada pela API na admissão (decisão 0098).
        requested_by, correlation_id = row["requested_by"], row["correlation_id"]

        if decision.remove:
            await store.delete_resource(resource_id)
            await self._add_updated(
                store,
                messages.updated(
                    resource_id,
                    lifecycle="absent",
                    phase="Deleting",
                    resource_version=row["resource_version"] + 1,
                    desired_generation=generation,
                    observed_generation=generation,
                    correlation_id=correlation_id,
                    removed=True,
                ),
                resource_id,
            )
            return False

        phase, conditions = decision.phase, decision.conditions
        reconciliation, failure_count = row["reconciliation"], row["failure_count"]
        suspended = False
        if decision.converged:
            failure_count = 0
        elif failure is not None:
            result = decide_result(
                failed=True,
                failure_reason=failure.reason,
                failure_limit=self._settings.loop.failure_limit,
                generation=generation,
                failure_count=failure_count,
                phase=phase,
                reconciliation=reconciliation,
                previous_conditions=conditions,
                now=now,
            )
            failure_count, phase, reconciliation = (
                result.failure_count,
                result.phase,
                result.reconciliation,
            )
            conditions, suspended = result.conditions, result.suspend
            if suspended:
                logger.warning(
                    "failure limit reached, reconciliation suspended",
                    extra={
                        "smarkee.resource.id": resource_id,
                        "smarkee.desired.generation": generation,
                        "smarkee.reason": failure.reason,
                    },
                )
        elif phase == "Pending":
            phase = "Reconciling"  # há trabalho em curso: a reconciliação começou

        observed_generation = generation if decision.converged else row["observed_generation"]
        changed = (
            (phase, conditions, reconciliation, failure_count, observation.presence)
            != (
                row["phase"],
                row["conditions"],
                row["reconciliation"],
                row["failure_count"],
                row["presence"],
            )
            or observation.data != row["observed"]
            or observed_generation != row["observed_generation"]
        )
        resource_version = await store.save_observation(
            resource_id,
            observed=observation.data,
            presence=observation.presence,
            observed_at=now,
            conditions=conditions,
            phase=phase,
            observed_generation=generation if decision.converged else None,
            failure_count=failure_count,
            reconciliation=reconciliation,
            changed=changed,
        )
        if suspended:
            await self._add_to_outbox(
                store,
                messages.suspended_desired(
                    resource_id,
                    desired=desired,
                    generation=generation,
                    requested_by=requested_by,
                    correlation_id=correlation_id,
                ),
                resource_id,
                "desired",
            )
        if changed:
            await self._add_updated(
                store,
                messages.updated(
                    resource_id,
                    lifecycle=lifecycle,
                    phase=phase,
                    resource_version=resource_version,
                    desired_generation=generation,
                    observed_generation=observed_generation,
                    correlation_id=correlation_id,
                ),
                resource_id,
            )
        return not decision.converged and not suspended

    def _log_deadlines(self, resource_id: str, generation: int, decision: ObservedDecision) -> None:
        extra = {
            "smarkee.resource.id": resource_id,
            "smarkee.desired.generation": generation,
            "smarkee.progress.deadline_seconds": self._settings.loop.progress_deadline_seconds,
        }
        if decision.progress_deadline_exceeded:
            logger.warning("progress deadline exceeded", extra=extra)
        if decision.observation_stale:
            logger.warning("observation stale", extra=extra)

    async def _add_updated(
        self, store: ControllerSsotStore, message: Mapping[str, Any], resource_id: str
    ) -> None:
        await self._add_to_outbox(store, message, resource_id, "updated")

    async def _add_to_outbox(
        self,
        store: ControllerSsotStore,
        message: Mapping[str, Any],
        resource_id: str,
        message_type: str,
    ) -> None:
        await store.add_to_outbox(
            message, resource_id=resource_id, subject=subject_of(message_type, resource_id)
        )

    def stop(self) -> None:
        self._stop.set()
        self._workqueue.close()

    async def shutdown(self) -> None:
        """Encerramento registrado em `close_after`: para os workers e cancela os retries."""
        self.stop()
