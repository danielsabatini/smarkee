"""Erros de domínio do Executor de `sum.service`."""


class ActionFailedError(Exception):
    """A ação não pode ser concluída. Vira o resultado `failed`, com o motivo (`reason`).

    `retryable` diz se repetir a ação pode resolver; a recusa do Executor é permanente.
    """

    def __init__(self, reason: str, *, retryable: bool, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.retryable = retryable
        self.message = message
