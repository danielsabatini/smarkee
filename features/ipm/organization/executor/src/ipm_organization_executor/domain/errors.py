"""Erros do domínio do Executor."""


class ActionFailedError(Exception):
    """A ação não pôde ser concluída. Vira a mensagem `failed` (`schemas/common/failed`)."""

    def __init__(self, reason: str, *, retryable: bool, message: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable
        self.message = message
