"""Streams e filtros lidos pelo Reconciler para reconstruir o estado (`docs/messaging/NATS.md`

§7.4)."""

STREAMS = (
    ("DESIRED", "manager.desired.core.account.>", "desired"),
    ("OBSERVED", "observer.observed.core.account.>", "observed"),
    ("RESULT", "executor.*.core.account.>", "result"),
)
"""(Stream, filtro, sufixo do consumer) de cada fonte de estado."""
