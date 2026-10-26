"""Streams e filtros lidos pelo Reconciler para reconstruir o estado (`docs/messaging/NATS.md`

§7.4)."""

STREAMS = (
    ("DESIRED", "manager.desired.ipm.role.>", "desired"),
    ("OBSERVED", "observer.observed.ipm.role.>", "observed"),
    ("RESULT", "executor.*.ipm.role.>", "result"),
)
"""(Stream, filtro, sufixo do consumer) de cada fonte de estado."""
