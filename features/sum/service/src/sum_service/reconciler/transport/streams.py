"""Streams e filtros lidos pelo Reconciler para reconstruir o estado (`docs/NATS.md` §7.4)."""

STREAMS = (
    ("DESIRED", "manager.desired.sum.service.>", "desired"),
    ("OBSERVED", "observer.observed.sum.service.>", "observed"),
    ("RESULT", "executor.*.sum.service.>", "result"),
)
"""(Stream, filtro, sufixo do consumer) de cada fonte de estado."""
