"""Streams e filtros lidos pelo Reconciler para reconstruir o estado (`docs/messaging/NATS.md`

§7.4)."""

STREAMS = (
    ("DESIRED", "manager.desired.ipm.user.>", "desired"),
    ("OBSERVED", "observer.observed.ipm.user.>", "observed"),
    ("RESULT", "executor.*.ipm.user.>", "result"),
)
"""(Stream, filtro, sufixo do consumer) de cada fonte de estado."""
