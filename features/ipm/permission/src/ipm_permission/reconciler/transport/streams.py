"""Streams e filtros lidos pelo Reconciler para reconstruir o estado (`docs/messaging/NATS.md`

§7.4)."""

STREAMS = (
    ("DESIRED", "manager.desired.ipm.permission.>", "desired"),
    ("OBSERVED", "observer.observed.ipm.permission.>", "observed"),
    ("RESULT", "executor.*.ipm.permission.>", "result"),
)
"""(Stream, filtro, sufixo do consumer) de cada fonte de estado."""
