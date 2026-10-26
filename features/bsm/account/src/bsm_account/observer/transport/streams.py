"""Streams e filtros lidos pelo Observer para reconstruir o estado (`docs/messaging/NATS.md` §7.4,

§7.6)."""

STREAMS = (
    ("DESIRED", "manager.desired.bsm.account.>", "desired"),
    ("RESULT", "executor.*.bsm.account.>", "result"),
)
"""(Stream, filtro, sufixo do consumer) de cada fonte de estado."""
