"""Streams e filtros lidos pelo Observer para reconstruir o estado (`docs/NATS.md` §7.4, §7.6)."""

STREAMS = (
    ("DESIRED", "manager.desired.ipm.permission.>", "desired"),
    ("RESULT", "executor.*.ipm.permission.>", "result"),
)
"""(Stream, filtro, sufixo do consumer) de cada fonte de estado."""
