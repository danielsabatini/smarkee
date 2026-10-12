"""Tipos do provedor de identidade que o domínio conhece (sem I/O)."""

from dataclasses import dataclass


class ProviderError(Exception):
    """A chamada ao Zitadel falhou. `reason` e `retryable` seguem o contrato `failed`."""

    def __init__(self, reason: str, *, retryable: bool, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ZitadelUser:
    email: str
    password_set: bool


@dataclass(frozen=True, slots=True)
class Grant:
    grant_id: str
    roles: frozenset[str]
