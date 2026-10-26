"""Streams e filtros lidos pelo Reconciler para reconstruir o estado (`docs/messaging/NATS.md`

§7.4)."""

STREAMS = (
    ("DESIRED", "manager.desired.@@DOTTED@@.>", "desired"),
    ("OBSERVED", "observer.observed.@@DOTTED@@.>", "observed"),
    ("RESULT", "executor.*.@@DOTTED@@.>", "result"),
)
"""(Stream, filtro, sufixo do consumer) de cada fonte de estado."""
