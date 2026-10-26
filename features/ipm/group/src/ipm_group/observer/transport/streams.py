"""Streams e filtros lidos pelo Observer para reconstruir o estado (`docs/NATS.md` §7.4, §7.6)."""

STREAMS = (
    ("DESIRED", "manager.desired.ipm.group.>", "desired"),
    ("RESULT", "executor.*.ipm.group.>", "result"),
)
"""(Stream, filtro, sufixo do consumer) de cada fonte de estado."""
