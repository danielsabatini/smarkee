"""Solicitante autenticado e as permissões do projeto do módulo (`roles-bsm`)."""

from dataclasses import dataclass

PAYMENT_CREATE = "bsm.payment.create"
PAYMENT_GET = "bsm.payment.get"
PAYMENT_LIST = "bsm.payment.list"
PAYMENT_UPDATE = "bsm.payment.update"
PAYMENT_DELETE = "bsm.payment.delete"
PAYMENT_OPERATE = "bsm.payment.operate"
PAYMENT_ADMIN = "bsm.payment.admin"  # retrocompatibilidade transitória


@dataclass(frozen=True, slots=True)
class Principal:
    """O usuário autenticado: o `sub` do token (ID do usuário) e as permissões no projeto."""

    subject: str
    permissions: frozenset[str]
    access_token: str

    @property
    def is_operator(self) -> bool:
        """Operadores agem em qualquer método de pagamento."""
        return PAYMENT_OPERATE in self.permissions or PAYMENT_ADMIN in self.permissions

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions
