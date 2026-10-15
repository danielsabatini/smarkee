"""Fase do recurso depois de uma observação (decisão 0033). Puro.

Ligação ativa convergida: o usuário tem todas as roles do serviço. Ligação desligada convergida: o
usuário não tem nenhuma role do serviço (inclusive quando o usuário já não existe). Observação
`unknown` não muda a fase: uma leitura inconclusiva não é prova de nada.
"""

from collections.abc import Collection


def phase_after_observation(
    *,
    lifecycle: str,
    desired_roles: Collection[str],
    presence: str,
    observed_roles: Collection[str],
) -> str | None:
    """`Ready` quando convergiu, `Reconciling` quando não. `None` se a observação é `unknown`."""
    if presence == "unknown":
        return None
    held = set(observed_roles)
    if lifecycle == "absent":
        converged = not held
    else:
        converged = presence == "present" and set(desired_roles) <= held
    return "Ready" if converged else "Reconciling"
