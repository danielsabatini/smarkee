"""Projeção local de uso de Grupos por usuários da Organization (decisão 0100).

Substitui a consulta HTTP à API de User. O `StateConsumer` entrega o último `desired` de cada
usuário (`manager.desired.ipm.user.>`), e esta projeção guarda quais grupos cada usuário possui
na sua Organization. No `DELETE`, a contagem de dependentes é síncrona e em memória.
"""

import json
import logging
from collections.abc import Mapping
from typing import Any, cast

from ipm_group.common.contracts.envelope import EnvelopeError, read_envelope

logger = logging.getLogger(__name__)

USER_SUBJECT = "desired.ipm.user.>"
"""Subject do `DESIRED` de que a projeção se alimenta."""

_PRESENT = "present"


class GroupUsageProjection:
    """Rastreia quais Grupos possuem usuários vinculados em cada Organization."""

    def __init__(self) -> None:
        # user_id -> (organization_id, set_of_groups)
        self._assignments: dict[str, tuple[str, frozenset[str]]] = {}
        # (organization_id, group_name) -> count of users
        self._counts: dict[tuple[str, str], int] = {}

    async def on_message(self, data: bytes) -> bool:
        """Aplica um evento `desired`; devolve `True` se a projeção mudou."""
        try:
            raw: Mapping[str, Any] = json.loads(data)
            envelope = read_envelope(raw)
        except (ValueError, EnvelopeError) as error:
            logger.warning("ignoring invalid group usage desired message", exc_info=error)
            return False
        if (
            envelope.message_type.value != "desired"
            or envelope.module != "ipm"
            or envelope.resource_type != "user"
        ):
            return False
        return self.apply(envelope.resource_id, envelope.data)

    def apply(self, resource_id: str, desired: Mapping[str, Any]) -> bool:
        org_id = desired.get("organizationId")
        lifecycle = desired.get("lifecycle")
        groups_raw = desired.get("groups")
        items = cast("list[object]", groups_raw) if isinstance(groups_raw, list) else []
        new_groups: frozenset[str] = frozenset(item for item in items if isinstance(item, str))

        old = self._assignments.get(resource_id)
        new_target = (
            (org_id, new_groups) if lifecycle == _PRESENT and isinstance(org_id, str) else None
        )

        if old == new_target:
            return False

        if old is not None:
            old_org, old_groups = old
            for group_name in old_groups:
                key = (old_org, group_name)
                c = self._counts.get(key, 0) - 1
                if c <= 0:
                    self._counts.pop(key, None)
                else:
                    self._counts[key] = c

        if new_target is not None:
            self._assignments[resource_id] = new_target
            new_org, target_groups = new_target
            for group_name in target_groups:
                key = (new_org, group_name)
                self._counts[key] = self._counts.get(key, 0) + 1
        else:
            self._assignments.pop(resource_id, None)

        return True

    def count_users_with_group(self, organization_id: str, group_name: str) -> int:
        """Quantidade de usuários ativos vinculados ao Grupo na Organization."""
        return self._counts.get((organization_id, group_name), 0)
