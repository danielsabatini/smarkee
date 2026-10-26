"""Rollout de Roles em `ipm.serviceaccount`: re-expande `permissions` quando `ipm.role` muda.

Decisões 0083 e 0094.

Quando uma Role composta (`ipm.role`) ou permissão delegável (`ipm.permission`) é alterada, cada
service account presente de uma Organization que referencia Roles cujas permissões efetivas
mudaram ganha
uma geração nova com Operation `update` (`system:catalog`), acionando o Reconciler e o Executor
para atualizar a autorização no Zitadel com as permissões atômicas expandidas.
"""

import hashlib
import json
import logging
from collections.abc import Callable, Collection, Mapping
from datetime import datetime
from typing import Any

from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from ipm_serviceaccount.common.contracts import generated
from ipm_serviceaccount.common.contracts.envelope import EnvelopeError, read_envelope
from ipm_serviceaccount.common.ids import new_identifier, utc_now
from ipm_serviceaccount.common.resource import MODULE, SCHEMA_VERSION
from ipm_serviceaccount.manager.domain.kind import ResourceKind
from ipm_serviceaccount.manager.domain.serviceaccount import ServiceAccountPolicy
from ipm_serviceaccount.manager.handlers.publishing import Publishing
from ipm_serviceaccount.manager.store.ssot import SsotStore
from ipm_serviceaccount.manager.store.tables import tables_of

logger = logging.getLogger(__name__)

SYSTEM_ACTOR = "system:catalog"
"""Quem pede o rollout de Roles: o próprio Manager ao reagir à mensageria (decisão 0083)."""


async def roll_out_serviceaccount_roles(
    pool: AsyncConnectionPool[Any],
    kind: ResourceKind,
    *,
    only: Collection[str] | None = None,
    clock: Callable[[], datetime] = utc_now,
    identifiers: Callable[[], str] = new_identifier,
) -> int:
    """Grava geração nova nas service accounts cujas `permissions` expandidas de `roles` mudaram."""
    policy = kind.policy
    if not isinstance(policy, ServiceAccountPolicy):
        raise TypeError("o rollout de roles é só da ServiceAccount")
    tables = tables_of(kind.resource_type)
    async with pool.connection() as connection:
        cursor = await connection.execute(
            sql.SQL("SELECT resource_id FROM {table} ORDER BY resource_id").format(
                table=tables.resource
            )
        )
        resource_ids = [str(row[0]) for row in await cursor.fetchall()]
    if only is not None:
        resource_ids = [resource_id for resource_id in resource_ids if resource_id in only]
    publishing = Publishing(clock, identifiers)
    changed = 0
    for resource_id in resource_ids:
        async with pool.connection() as connection:
            store = SsotStore(connection, tables)
            async with store.transaction():
                row = await store.lock_for_request(resource_id)
                if row is None:
                    continue
                desired = policy.rolled_out(row["desired"])
                if desired is None:
                    continue
                generation = await store.change_desired(
                    resource_id,
                    desired=desired,
                    reconciliation="active",
                    phase="Reconciling",
                    expected_resource_version=row["resource_version"],
                )
                if generation is None:
                    continue
                operation_id, correlation_id = identifiers(), identifiers()
                await store.insert_operation(
                    operation_id=operation_id,
                    resource_id=resource_id,
                    operation_type="update",
                    generation=generation,
                    requested_by=SYSTEM_ACTOR,
                    correlation_id=correlation_id,
                    request_digest=hashlib.sha256(
                        json.dumps(desired, sort_keys=True).encode()
                    ).hexdigest(),
                    status="accepted",
                    reason=None,
                    completed_at=None,
                )
                await publishing.desired(
                    store,
                    kind,
                    _cause(resource_id, operation_id, correlation_id, clock()),
                    desired=desired,
                    reconciliation="active",
                    generation=generation,
                )
        changed += 1
        logger.info(
            "serviceaccount roles rolled out",
            extra={
                "smarkee.resource.id": resource_id,
                "smarkee.desired.generation": generation,
                "smarkee.operation.id": operation_id,
            },
        )
    logger.info(
        "serviceaccount roles rollout finished", extra={"smarkee.serviceaccounts.changed": changed}
    )
    return changed


def _cause(
    resource_id: str, operation_id: str, correlation_id: str, now: datetime
) -> generated.MessageEnvelope:
    """Pedido do sistema que causa a geração nova no rollout de Roles."""
    return generated.MessageEnvelope.model_validate(
        {
            "messageId": operation_id,
            "schemaVersion": SCHEMA_VERSION,
            "messageType": "requested",
            "emitter": "manager",
            "module": MODULE,
            "resourceType": "serviceaccount",
            "resourceId": resource_id,
            "operation": "update",
            "requestedBy": SYSTEM_ACTOR,
            "correlationId": correlation_id,
            "occurredAt": now.isoformat(),
            "publishedAt": now.isoformat(),
            "data": {},
        }
    )


class RoleCatalogWatcher:
    """Observa `manager.desired.ipm.role.>` e `manager.desired.ipm.permission.>` (decisão 0083).

    Atualiza o `AccessCatalog` da `ServiceAccountPolicy` e dispara `roll_out_serviceaccount_roles`
    sempre que o
    catálogo de Roles ou de permissões delegáveis muda.
    """

    def __init__(
        self,
        pool: AsyncConnectionPool[Any],
        kind: ResourceKind,
        *,
        clock: Callable[[], datetime] = utc_now,
        identifiers: Callable[[], str] = new_identifier,
    ) -> None:
        policy = kind.policy
        if not isinstance(policy, ServiceAccountPolicy):
            raise TypeError("RoleCatalogWatcher exige ServiceAccountPolicy")
        self._pool = pool
        self._kind = kind
        self._policy = policy
        self._clock = clock
        self._identifiers = identifiers

    async def on_message(self, data: bytes) -> int:
        try:
            raw: Mapping[str, Any] = json.loads(data)
            envelope = read_envelope(raw)
        except (ValueError, EnvelopeError) as error:
            logger.warning("ignoring invalid catalog desired message", exc_info=error)
            return 0
        if envelope.message_type.value != "desired" or envelope.module != MODULE:
            return 0
        payload = envelope.data
        catalog = self._policy.catalog
        if envelope.resource_type == "permission":
            changed = catalog.apply_permission_desired(envelope.resource_id, payload)
        elif envelope.resource_type == "role":
            changed = catalog.apply_role_desired(envelope.resource_id, payload)
        else:
            return 0
        if not changed:
            return 0
        return await roll_out_serviceaccount_roles(
            self._pool,
            self._kind,
            clock=self._clock,
            identifiers=self._identifiers,
        )
