"""Convergência da ligação de serviço (decisões 0033 e 0079). Puro.

Ligação ativa convergida: o usuário tem todas as `serviceRoles` e nenhuma das outras roles que a
ligação controla (`managedRoles`, por exemplo uma que saiu do catálogo). Ligação desligada
convergida: o usuário não tem nenhuma role que a ligação controla, inclusive quando ele já não
existe no provedor.
"""

from collections.abc import Mapping
from typing import Any, cast

from sum_service.common.contracts import generated


def _roles(value: object) -> set[str]:
    return {str(role) for role in cast("list[object]", value)} if isinstance(value, list) else set()


class ServicePolicy:
    def message_data(self, desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
        model = generated.ServiceDesiredData.model_validate(
            {**desired, "reconciliation": reconciliation}
        )
        return model.model_dump(mode="json", by_alias=True, exclude_none=True)

    def is_converged(
        self, desired: Mapping[str, Any], presence: str, observed: Mapping[str, Any] | None
    ) -> bool:
        held = _roles((observed or {}).get("serviceRoles"))
        wanted = _roles(desired.get("serviceRoles"))
        managed = _roles(desired.get("managedRoles", desired.get("serviceRoles")))
        if desired.get("lifecycle") == "absent":
            return presence == "absent" or not held & managed
        return presence == "present" and wanted <= held and not held & (managed - wanted)
