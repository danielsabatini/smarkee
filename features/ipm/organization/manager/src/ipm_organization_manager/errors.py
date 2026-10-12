"""Erros do Manager."""


class PermanentMessageError(Exception):
    """A mensagem é inválida e nunca será válida: não deve ser reprocessada em ciclo.

    Segue a política de quarentena do transporte (`docs/SCHEMA.md` §21.1). A mensagem não
    contém valores `confidential`: só identifica o campo e a regra violada.
    """
