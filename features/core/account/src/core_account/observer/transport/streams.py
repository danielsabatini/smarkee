"""Streams e filtros lidos pelo Observer para reconstruir o estado (`docs/messaging/NATS.md` §7.4,

§7.6)."""

STREAMS = (
    ("DESIRED", "manager.desired.core.account.>", "desired"),
    ("RESULT", "executor.*.core.account.>", "result"),
)
"""(Stream, filtro, sufixo do consumer) de cada fonte de estado."""
