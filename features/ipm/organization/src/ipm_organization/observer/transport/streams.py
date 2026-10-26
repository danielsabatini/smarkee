"""Streams e filtros lidos pelo Observer para reconstruir o estado (`docs/messaging/NATS.md` §7.4,

§7.6)."""

STREAMS = (
    ("DESIRED", "manager.desired.ipm.organization.>", "desired"),
    ("RESULT", "executor.*.ipm.organization.>", "result"),
)
"""(Stream, filtro, sufixo do consumer) de cada fonte de estado."""
