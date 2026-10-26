"""Streams e filtros lidos pelo Reconciler para reconstruir o estado (`docs/messaging/NATS.md`

§7.4)."""

STREAMS = (
    ("DESIRED", "manager.desired.ipm.organization.>", "desired"),
    ("OBSERVED", "observer.observed.ipm.organization.>", "observed"),
    ("RESULT", "executor.*.ipm.organization.>", "result"),
)
"""(Stream, filtro, sufixo do consumer) de cada fonte de estado."""
