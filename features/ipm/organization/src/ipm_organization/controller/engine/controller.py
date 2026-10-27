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
from ipm_organization.common.ids import new_identifier, utc_now
from ipm_organization.common.logging_config import bind_context, restore_context, save_context
from ipm_organization.common.resource import MODULE, RESOURCE_TYPE
from ipm_organization.controller.domain.convergence import decide_convergence
from ipm_organization.controller.domain.decision import DesiredState, ObservedState, decide
from ipm_organization.controller.drivers.identity import ProviderError
from ipm_organization.controller.drivers.metadata import MetadataDriver
from ipm_organization.controller.drivers.organization import OrganizationDriver
from ipm_organization.controller.drivers.user_access import UserAccessDriver
from ipm_organization.controller.engine.actions import ActionFailedError, execute
from ipm_organization.controller.engine.observation import observe_organization
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
        clock: Callable[[], datetime] = utc_now,
        identifiers: Callable[[], str] = new_identifier,
    ) -> None:
        self._pool = pool
        self._drivers = drivers
        self._settings = settings
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
                "SELECT resource_id FROM ipm.organization WHERE lifecycle = 'present'"
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
                    await self.reconcile(resource_id)
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

    async def reconcile(self, resource_id: str) -> None:
        """Executa o ciclo atômico de reconciliação de uma Organization."""
        async with self._pool.connection() as conn:
            store = ControllerSsotStore(conn)
            async with store.transaction():
                row = await store.lock_resource(resource_id)
                if row is None:
                    return

                desired: Mapping[str, Any] = row["desired"]
                generation: int = row["desired_generation"]
                lifecycle: str = row["lifecycle"]
                reconciliation: str = row["reconciliation"]

                if reconciliation == "suspended":
                    return

                # 1. Observar
                obs_res = await observe_organization(
                    resource_id,
                    organizations=self._drivers.organizations,
                    metadata=self._drivers.metadata,
                    user_access=self._drivers.user_access,
                )

                # 2. Decidir
                desired_state = DesiredState(
                    lifecycle=lifecycle,
                    name=str(desired.get("name", "")),
                    platform_access=str(desired.get("platformAccess", "granted")),
                    deletion_protection=desired.get("deletionProtection", True) is not False,
                    user_access=desired.get("userAccess"),
                )
                observed_state = ObservedState(
                    presence=obs_res.presence,
                    name=obs_res.data.get("name"),
                    platform_access=obs_res.data.get("platformAccess"),
                    deletion_protection=obs_res.data.get("deletionProtection"),
                    user_access=obs_res.data.get("userAccess"),
                )

                action = decide(desired_state, observed_state)
                action_failure: ActionFailedError | None = None

                # 3. Agir e reobservar se houver divergência
                if action is not None:
                    try:
                        await execute(
                            action.operation,
                            resource_id,
                            desired,
                            organizations=self._drivers.organizations,
                            metadata=self._drivers.metadata,
                            user_access=self._drivers.user_access,
                        )
                    except ActionFailedError as err:
                        action_failure = err
                    except ProviderError as err:
                        action_failure = ActionFailedError(
                            err.reason, retryable=err.retryable, message=str(err)
                        )

                    # Reobserva imediatamente após a ação
                    obs_res = await observe_organization(
                        resource_id,
                        organizations=self._drivers.organizations,
                        metadata=self._drivers.metadata,
                        user_access=self._drivers.user_access,
                    )

                # 4. Calcular convergência
                conv = decide_convergence(
                    desired=desired,
                    lifecycle=lifecycle,
                    generation=generation,
                    presence=obs_res.presence,
                    observed=obs_res.data,
                    previous_phase=row["phase"],
                    previous_conditions=row["conditions"],
                    now=self._clock(),
                    progress_deadline_seconds=self._settings.loop.progress_deadline_seconds,
                )

                # 5. Persistir desfecho no SSOT
                if conv.converged and lifecycle == "absent":
                    await store.delete_resource(resource_id)
                    await store.settle_operations(resource_id, generation, converged=True)
                else:
                    await store.save_observation(
                        resource_id,
                        observed=obs_res.data,
                        presence=obs_res.presence,
                        observed_at=self._clock(),
                        conditions=conv.conditions,
                        phase=conv.phase,
                        observed_generation=conv.observed_generation,
                    )
                    if action_failure is not None:
                        await store.record_failure(resource_id, count=row["failure_count"] + 1)
                    elif conv.converged:
                        await store.clear_failures(resource_id)

                    await store.settle_operations(resource_id, generation, converged=conv.converged)

    def stop(self) -> None:
        self._stop.set()
        self._workqueue.close()

    async def shutdown(self) -> None:
        """Encerramento registrado em `close_after`: para os workers e cancela os retries."""
        self.stop()
