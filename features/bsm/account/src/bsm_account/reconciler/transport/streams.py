"""Streams e filtros lidos pelo Reconciler para reconstruir o estado (`docs/messaging/NATS.md`

§7.4)."""

STREAMS = (
    ("DESIRED", "manager.desired.bsm.account.>", "desired"),
    ("OBSERVED", "observer.observed.bsm.account.>", "observed"),
    ("RESULT", "executor.*.bsm.account.>", "result"),
)
"""(Stream, filtro, sufixo do consumer) de cada fonte de estado."""
