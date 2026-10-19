"""Streams e filtros lidos pelo Observer para reconstruir o estado (`docs/NATS.md` §7.4)."""

STREAMS = (
    ("DESIRED", "manager.desired.sum.service.>", "desired"),
    ("RESULT", "executor.*.sum.service.>", "result"),
)
"""(Stream, filtro, sufixo do consumer) de cada fonte de estado."""
