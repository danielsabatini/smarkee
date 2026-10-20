"""Regras de negócio da Account, aplicadas pelo Manager (decisão 0014).

Puro: sem banco, rede ou relógio. A unicidade do e-mail é declarada aqui (`unique_value`) e
verificada pelo adaptador do SSOT.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from core_account.common.contracts import generated
from core_account.common.contracts.base import ContractModel, fields_of, validate_tolerant
from core_account.manager.domain.errors import PermanentMessageError
from core_account.manager.domain.policy import Request, UniqueValue


def _validated[M: ContractModel](model: type[M], data: Mapping[str, Any], *, label: str) -> M:
    try:
        return validate_tolerant(model, data)
    except ValidationError as error:
        raise PermanentMessageError(f"{label} inválido nos campos: {fields_of(error)}") from None


def normalize_email(email: str) -> str:
    """Regra de normalização `lowercase` (com `trim`) do e-mail, também o nome de login."""
    return email.strip().lower()


def _parse_resource_version(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise PermanentMessageError("resourceVersion não numérico") from None


DEFAULT_PLATFORM_ROLES: tuple[str, ...] = (
    "core.account.delete",
    "core.account.get",
    "sum.ipm.disable",
    "sum.ipm.enable",
    "sum.ipm.get",
)
"""Roles de ação do usuário cadastrado (decisões 0025, 0032 e 0033).

São as do módulo `core` e as roles base do SUM, que só permitem **pedir** a ligação de um serviço.
As roles dos serviços (por exemplo, `ipm.organization.*`) não vêm no cadastro: chegam quando o
usuário liga o serviço (SUM), concedidas por quem tem o Project Grant daquele módulo.
"""


class AccountPolicy:
    """Account: e-mail único (normalizado) e `desired` de remoção sem dados pessoais (decisão 0014).

    As roles que o usuário recebe vêm da configuração do Manager e ficam gravadas no `desired`
    (`platformRoles`, decisão 0025): é a única fonte do conjunto no loop.
    """

    def __init__(self, platform_roles: tuple[str, ...] = DEFAULT_PLATFORM_ROLES) -> None:
        self._platform_roles = sorted(set(platform_roles))

    def parse(self, operation: str, data: Mapping[str, Any]) -> Request:
        match operation:
            case "create":
                create = _validated(
                    generated.AccountRequestedCreateData, data, label="requested/create"
                )
                return Request(
                    "create",
                    create.operation_id,
                    create.request_digest,
                    specification={
                        "givenName": create.specification.given_name,
                        "familyName": create.specification.family_name,
                        "email": normalize_email(str(create.specification.email)),
                    },
                )
            case "update":
                update = _validated(
                    generated.AccountRequestedUpdateData, data, label="requested/update"
                )
                return Request(
                    "update",
                    update.operation_id,
                    update.request_digest,
                    resource_version=_parse_resource_version(update.resource_version),
                    specification={"deletionProtection": update.specification.deletion_protection},
                )
            case "delete":
                delete = _validated(
                    generated.AccountRequestedDeleteData, data, label="requested/delete"
                )
                return Request(
                    "delete",
                    delete.operation_id,
                    delete.request_digest,
                    resource_version=_parse_resource_version(delete.resource_version),
                )
            case _:
                raise PermanentMessageError(f"operação não suportada para account: {operation}")

    def desired_for_create(self, request: Request, requested_by: str) -> dict[str, Any]:
        assert request.specification is not None  # noqa: S101 (invariante de parse)
        return {
            "lifecycle": "present",
            "platformAccess": "granted",
            "platformRoles": list(self._platform_roles),
            "deletionProtection": True,  # todo recurso apagável nasce protegido (decisão 0043)
            **request.specification,
        }

    def desired_for_update(self, current: Mapping[str, Any], request: Request) -> dict[str, Any]:
        # A única alteração possível na Account é a proteção contra exclusão (decisão 0043).
        return {**current, **(request.specification or {})}

    def desired_for_delete(self, current: Mapping[str, Any]) -> dict[str, Any]:
        # Sem dados pessoais: o Executor só precisa do resourceId para remover o usuário.
        return {
            "lifecycle": "absent",
            "platformAccess": current["platformAccess"],
            "platformRoles": current["platformRoles"],
        }

    def unique_value(self, desired: Mapping[str, Any]) -> UniqueValue | None:
        if desired["lifecycle"] != "present":
            return None
        email: str = desired["email"]
        return UniqueValue(field="email", value=email, lock_key=f"core.account.email:{email}")

    def deletion_protected(self, current: Mapping[str, Any]) -> bool:
        return current.get("deletionProtection", True) is not False

    def message_data(self, desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
        model = generated.AccountDesiredData.model_validate(
            {**desired, "reconciliation": reconciliation}
        )
        return model.model_dump(mode="json", exclude_none=True)

    def is_converged(
        self, desired: Mapping[str, Any], presence: str, observed: Mapping[str, Any] | None
    ) -> bool:
        # Campos gerenciados da Account: `lifecycle`, `platformAccess`, `platformRoles` e
        # `deletionProtection`, este pelo metadado (schemas/core/account/desired; decisão 0074). As
        # roles desejadas precisam estar contidas nas observadas: roles a mais não divergem.
        if desired["lifecycle"] == "absent":
            return presence == "absent"
        return (
            presence == "present"
            and observed is not None
            and observed.get("platformAccess") == desired["platformAccess"]
            and set(desired["platformRoles"]) <= set(observed.get("platformRoles", ()))
            and observed.get("deletionProtection") == self.deletion_protected(desired)
        )
