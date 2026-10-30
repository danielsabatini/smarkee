"""Regras de negócio da Account, aplicadas na admissão síncrona (decisões 0014 e 0098).

Puro: sem banco, rede ou relógio. A unicidade do e-mail entre as contas ativas é declarada aqui
(`unique_value`) e verificada na mesma transação da admissão pelo adaptador do SSOT
(`docs/data/SSOT.md` §10.1).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core_account.common.contracts import generated

PERSONAL_FIELDS = ("givenName", "familyName", "email")
"""Dados pessoais do `desired`: saem dele na remoção (`schemas/core/account/desired`)."""

DEFAULT_PLATFORM_PERMISSIONS: tuple[str, ...] = (
    "bsm.account.create",
    "bsm.account.delete",
    "bsm.account.get",
    "bsm.account.list",
    "bsm.account.update",
    "core.account.delete",
    "core.account.get",
    "sum.ipm.disable",
    "sum.ipm.enable",
    "sum.ipm.get",
)
"""Permissões de ação do usuário cadastrado (decisões 0025, 0032, 0033 e 0082).

São as dos módulos de nível de conta (`core` e `bsm`, fundacionais da pessoa) e as permissões base
do SUM, que só permitem **pedir** a ligação de um serviço. As permissões dos serviços ligáveis (por
exemplo, `ipm.organization.*`) não vêm no cadastro: chegam quando o usuário liga o serviço (SUM),
concedidas por quem tem o Project Grant daquele módulo.
"""


@dataclass(frozen=True, slots=True)
class UniqueValue:
    """Valor que não pode se repetir entre as Accounts ativas."""

    field: str
    value: str
    lock_key: str
    """Chave que serializa as transações que disputam o mesmo valor."""


def normalize_email(email: str) -> str:
    """Regra de normalização `lowercase` (com `trim`) do e-mail, também o nome de login."""
    return email.strip().lower()


def desired_for_create(specification: Mapping[str, Any]) -> dict[str, Any]:
    # Todo recurso apagável nasce protegido contra exclusão (decisão 0043).
    return {"lifecycle": "present", "deletionProtection": True, **specification}


def desired_for_update(current: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    # A única alteração possível na Account é a proteção contra exclusão (decisão 0043).
    return {**current, **changes}


def desired_for_delete(current: Mapping[str, Any]) -> dict[str, Any]:
    # Sem dados pessoais: o Controller só precisa do resourceId para remover o usuário.
    return {
        "lifecycle": "absent",
        "platformAccess": current["platformAccess"],
        "platformPermissions": current["platformPermissions"],
    }


REGISTRATION_TICKET_TTL_SECONDS = 1800
RESEND_MIN_INTERVAL_SECONDS = 60


def mask_email(email: str) -> str:
    """Mascara o e-mail para conferência sem expor o endereço completo (ex: a***a@empresa.com)."""
    clean = email.strip()
    if "@" not in clean:
        return f"{clean[:1]}***" if clean else "***"
    local_part, domain = clean.split("@", 1)
    if len(local_part) <= 1:
        masked_local = f"{local_part}***"
    else:
        masked_local = f"{local_part[0]}***{local_part[-1]}"
    return f"{masked_local}@{domain}"


def unique_value(desired: Mapping[str, Any]) -> UniqueValue | None:
    """O e-mail normalizado é o nome de login: único entre as contas ativas."""
    if desired["lifecycle"] != "present":
        return None
    email: str = desired["email"]
    return UniqueValue(field="email", value=email, lock_key=f"core.account.email:{email}")


def deletion_protected(current: Mapping[str, Any]) -> bool:
    # Registro sem o campo (anterior à proteção) conta como protegido.
    return current.get("deletionProtection", True) is not False


def message_data(desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
    model = generated.AccountDesiredData.model_validate(
        {**desired, "reconciliation": reconciliation}
    )
    return model.model_dump(mode="json", exclude_none=True)
