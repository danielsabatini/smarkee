"""Projeção local do uso de Roles por usuários, grupos e service accounts (decisão 0100).

Substitui as consultas HTTP paginadas às APIs parceiras. O `StateConsumer` entrega o último
`desired` de cada recurso consumidor (`user`, `serviceaccount`, `group`), e esta projeção guarda
quais roles cada recurso usa na sua Organization. No `DELETE`, a resposta é síncrona e em memória.
"""

import json
import logging
from collections.abc import Mapping
from typing import Any, cast

from ipm_role.common.contracts.envelope import EnvelopeError, read_envelope

logger = logging.getLogger(__name__)

USER_SUBJECT = "manager.desired.ipm.user.>"
SERVICEACCOUNT_SUBJECT = "manager.desired.ipm.serviceaccount.>"
GROUP_SUBJECT = "manager.desired.ipm.group.>"
"""Subjects do `DESIRED` de que a projeção se alimenta."""

_CONSUMER_TYPES = frozenset({"user", "serviceaccount", "group"})
_PRESENT = "present"


class RoleUsageProjection:
    """Rastreia quais Roles estão atribuídas a recursos de cada Organization."""

    def __init__(self) -> None:
        self._assignments: dict[str, tuple[str, frozenset[str]]] = {}
        self._counts: dict[tuple[str, str], int] = {}

    async def on_message(self, data: bytes) -> bool:
        """Aplica um evento `desired`; devolve `True` se a projeção mudou."""
        try:
            raw: Mapping[str, Any] = json.loads(data)
            envelope = read_envelope(raw)
        except (ValueError, EnvelopeError) as error:
            logger.warning("ignoring invalid role usage desired message", exc_info=error)
            return False
        if (
            envelope.message_type.value != "desired"
            or envelope.module != "ipm"
            or envelope.resource_type not in _CONSUMER_TYPES
        ):
            return False
        return self.apply(envelope.resource_id, envelope.data)

    def apply(self, resource_id: str, desired: Mapping[str, Any]) -> bool:
        org_id = desired.get("organizationId")
        lifecycle = desired.get("lifecycle")
        roles_raw = desired.get("roles")
        items = cast("list[object]", roles_raw) if isinstance(roles_raw, list) else []
        new_roles: frozenset[str] = frozenset(item for item in items if isinstance(item, str))

        old = self._assignments.get(resource_id)
        new_target = (
            (org_id, new_roles) if lifecycle == _PRESENT and isinstance(org_id, str) else None
        )

        if old == new_target:
            return False

        if old is not None:
            old_org, old_roles = old
            for role_name in old_roles:
                key = (old_org, role_name)
                c = self._counts.get(key, 0) - 1
                if c <= 0:
                    self._counts.pop(key, None)
                else:
                    self._counts[key] = c

        if new_target is not None:
            self._assignments[resource_id] = new_target
            new_org, target_roles = new_target
            for role_name in target_roles:
                key = (new_org, role_name)
                self._counts[key] = self._counts.get(key, 0) + 1
        else:
            self._assignments.pop(resource_id, None)

        return True

    def is_role_in_use(self, organization_id: str, role_name: str) -> bool:
        """`True` se algum usuário, grupo ou service account ativo usa a Role."""
        return self._counts.get((organization_id, role_name), 0) > 0
