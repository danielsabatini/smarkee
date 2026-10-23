"""Organizations vinculadas à Billing Account vistas pelo Receiver, sem I/O (decisão 0082)."""


class OrganizationsCheckError(Exception):
    """O Receiver de Organization não respondeu de forma conclusiva. Na dúvida, não segue."""

    def __init__(self, *, retryable: bool) -> None:
        super().__init__("organizations attached to the billing account could not be verified")
        self.retryable = retryable
