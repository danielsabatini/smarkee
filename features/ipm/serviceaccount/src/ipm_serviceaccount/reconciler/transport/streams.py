"""Streams e filtros lidos pelo Reconciler para reconstruir o estado (`docs/messaging/NATS.md`

§7.4)."""

STREAMS = (
    ("DESIRED", "manager.desired.ipm.serviceaccount.>", "desired"),
    ("OBSERVED", "observer.observed.ipm.serviceaccount.>", "observed"),
    ("RESULT", "executor.*.ipm.serviceaccount.>", "result"),
)
"""(Stream, filtro, sufixo do consumer) de cada fonte de estado."""
