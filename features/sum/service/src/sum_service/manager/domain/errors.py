"""Erros do domínio do Manager do SUM."""


class PermanentMessageError(Exception):
    """A mensagem nunca será aceita como está: o transporte a retira do fluxo (`term`)."""
