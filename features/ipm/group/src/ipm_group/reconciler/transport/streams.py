"""Streams e filtros lidos pelo Reconciler para reconstruir o estado (`docs/messaging/NATS.md`

§7.4)."""

STREAMS = (
    ("DESIRED", "manager.desired.ipm.group.>", "desired"),
    ("OBSERVED", "observer.observed.ipm.group.>", "observed"),
    ("RESULT", "executor.*.ipm.group.>", "result"),
)
"""(Stream, filtro, sufixo do consumer) de cada fonte de estado."""
