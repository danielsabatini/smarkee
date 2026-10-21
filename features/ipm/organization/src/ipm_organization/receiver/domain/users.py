"""Usuários da Organization vistos pelo Receiver da Organization, sem I/O (decisão 0077)."""


class UsersCheckError(Exception):
    """O Receiver do User não respondeu de forma conclusiva. Na dúvida, o pedido não segue."""

    def __init__(self, *, retryable: bool) -> None:
        super().__init__("users of the organization could not be verified")
        self.retryable = retryable
