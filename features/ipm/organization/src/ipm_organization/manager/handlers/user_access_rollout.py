"""Rollout do `userAccess`: cada Organization segue o catálogo e as contas de agora (decisão 0081).

Como o rollout do SUM (decisão 0079) e o de um Deployment do Kubernetes quando o template muda: na
partida do Manager, antes dos consumers, cada Organization presente cujo `desired` difere do
`userAccess` de agora ganha uma geração nova, com uma Operation `update` do sistema, e o loop
aplica a mudança. Uma Organization criada antes da decisão 0081 passa a ter o Project Grant e os
papéis do `ipm/user`; um catálogo novo chega a todas.

Cada Organization é uma unidade atômica com a linha bloqueada: repetir (outra instância, reinício)
não grava nada de novo, porque o `desired` já é o de agora.
"""

import hashlib
import json
import logging
from collections.abc import Callable, Collection, Mapping
from datetime import datetime
from typing import Any

from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from ipm_organization.common.contracts import generated
from ipm_organization.common.contracts.envelope import EnvelopeError, read_envelope
from ipm_organization.common.ids import new_identifier, utc_now
from ipm_organization.common.resource import MODULE, SCHEMA_VERSION
from ipm_organization.manager.domain.kind import ResourceKind
from ipm_organization.manager.domain.organization import OrganizationPolicy
from ipm_organization.manager.handlers.publishing import Publishing
from ipm_organization.manager.store.ssot import SsotStore
from ipm_organization.manager.store.tables import tables_of

logger = logging.getLogger(__name__)

SYSTEM_ACTOR = "system:catalog"
"""Quem pede o rollout: o próprio Manager, pelo contrato e pela configuração (não há usuário)."""


async def roll_out_user_access(
    pool: AsyncConnectionPool[Any],
    kind: ResourceKind,
    *,
    only: Collection[str] | None = None,
    clock: Callable[[], datetime] = utc_now,
    identifiers: Callable[[], str] = new_identifier,
) -> int:
    """Grava a geração nova nas Organizations que o `userAccess` mudou. Devolve quantas mudaram.

    `only` limita o rollout a esses `resourceId` (testes contra o banco de dev, que não podem tocar
    as Organizations de verdade); a partida do Manager não o usa.
    """
    policy = kind.policy
    if not isinstance(policy, OrganizationPolicy):
        raise TypeError("o rollout do userAccess é só da Organization")
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
                    continue  # removida entre a lista e a trava
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
                    continue  # defensivo: a linha está bloqueada e a versão foi lida agora
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
            "user access rolled out to the organization",
            extra={
                "smarkee.resource.id": resource_id,
                "smarkee.desired.generation": generation,
                "smarkee.operation.id": operation_id,
            },
        )
    logger.info("user access rollout finished", extra={"smarkee.organizations.changed": changed})
    return changed


def _cause(
    resource_id: str, operation_id: str, correlation_id: str, now: datetime
) -> generated.MessageEnvelope:
    """Pedido do sistema que causa a geração nova: o solicitante e a correlação do `desired`."""
    return generated.MessageEnvelope.model_validate(
        {
            "messageId": operation_id,
            "schemaVersion": SCHEMA_VERSION,
            "messageType": "requested",
            "emitter": "manager",
            "module": MODULE,
            "resourceType": "organization",
            "resourceId": resource_id,
            "operation": "update",
            "requestedBy": SYSTEM_ACTOR,
            "correlationId": correlation_id,
            "occurredAt": now.isoformat(),
            "publishedAt": now.isoformat(),
            "data": {},
        }
    )


class PermissionCatalogWatcher:
    """Observa `manager.desired.ipm.permission.>` e propaga `grantable` às Organizations (0083).

    Inicializa o catálogo em memória com as permissões atuais da `OrganizationPolicy` (semente do
    contrato) e aplica cada `desired` de `ipm.permission`. Quando o conjunto de permissões
    `ipm.*` presentes com `grantable = true` muda, atualiza a `OrganizationPolicy` e dispara
    `roll_out_user_access` sem exigir redeploy.
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
        if not isinstance(policy, OrganizationPolicy):
            raise TypeError("PermissionCatalogWatcher exige OrganizationPolicy")
        self._pool = pool
        self._kind = kind
        self._policy = policy
        self._clock = clock
        self._identifiers = identifiers
        self._grantable: set[str] = set(policy.grant_permissions)
        self._names_by_id: dict[str, str] = {}

    async def on_message(self, data: bytes) -> int:
        try:
            raw: Mapping[str, Any] = json.loads(data)
            envelope = read_envelope(raw)
        except (ValueError, EnvelopeError) as error:
            logger.warning("ignoring invalid permission desired message", exc_info=error)
            return 0
        if (
            envelope.message_type.value != "desired"
            or envelope.module != MODULE
            or envelope.resource_type != "permission"
        ):
            return 0
        payload = envelope.data
        name = payload.get("name")
        if isinstance(name, str) and name:
            previous = self._names_by_id.get(envelope.resource_id)
            if previous and previous != name:
                self._grantable.discard(previous)
            self._names_by_id[envelope.resource_id] = name
        else:
            name = self._names_by_id.get(envelope.resource_id)
        if not isinstance(name, str) or not name.startswith(f"{MODULE}."):
            return 0
        is_grantable = payload.get("lifecycle") == "present" and payload.get("grantable") is True
        if is_grantable:
            self._grantable.add(name)
        else:
            self._grantable.discard(name)
        if not self._policy.update_grant_permissions(self._grantable):
            return 0
        return await roll_out_user_access(
            self._pool,
            self._kind,
            clock=self._clock,
            identifiers=self._identifiers,
        )
