"""Regras de negócio do User, aplicadas pelo Manager (decisão 0014).

Puro: sem banco, rede ou relógio. A unicidade do e-mail é declarada aqui (`unique_value`) e
verificada pelo adaptador do SSOT.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from core_user_manager.contracts import generated
from core_user_manager.contracts.base import ContractModel
from core_user_manager.domain.errors import PermanentMessageError
from core_user_manager.domain.policy import Request, UniqueValue


def _validated[M: ContractModel](model: type[M], data: Mapping[str, Any], *, label: str) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as error:
        fields = ", ".join(".".join(str(part) for part in item["loc"]) for item in error.errors())
        raise PermanentMessageError(f"{label} inválido nos campos: {fields}") from None


def normalize_email(email: str) -> str:
    """Regra de normalização `lowercase` (com `trim`) do e-mail, também o nome de login."""
    return email.strip().lower()


def _parse_resource_version(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise PermanentMessageError("resourceVersion não numérico") from None


class UserPolicy:
    """User: e-mail único (normalizado) e `desired` de remoção sem dados pessoais (decisão 0014)."""

    def parse(self, operation: str, data: Mapping[str, Any]) -> Request:
        match operation:
            case "create":
                create = _validated(
                    generated.UserRequestedCreateData, data, label="requested/create"
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
            case "delete":
                delete = _validated(
                    generated.UserRequestedDeleteData, data, label="requested/delete"
                )
                return Request(
                    "delete",
                    delete.operation_id,
                    delete.request_digest,
                    resource_version=_parse_resource_version(delete.resource_version),
                )
            case _:
                raise PermanentMessageError(f"operação não suportada para user: {operation}")

    def desired_for_create(self, request: Request, requested_by: str) -> dict[str, Any]:
        assert request.specification is not None  # noqa: S101 (invariante de parse)
        return {"lifecycle": "present", "platformAccess": "granted", **request.specification}

    def desired_for_update(self, current: Mapping[str, Any], request: Request) -> dict[str, Any]:
        raise PermanentMessageError("update não é suportado para user")

    def desired_for_delete(self, current: Mapping[str, Any]) -> dict[str, Any]:
        # Sem dados pessoais: o Executor só precisa do resourceId para remover o usuário.
        return {"lifecycle": "absent", "platformAccess": current["platformAccess"]}

    def unique_value(self, desired: Mapping[str, Any]) -> UniqueValue | None:
        if desired["lifecycle"] != "present":
            return None
        email: str = desired["email"]
        return UniqueValue(field="email", value=email, lock_key=f"core.user.email:{email}")

    def message_data(self, desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
        model = generated.UserDesiredData.model_validate(
            {**desired, "reconciliation": reconciliation}
        )
        return model.model_dump(mode="json", exclude_none=True)

    def is_converged(
        self, desired: Mapping[str, Any], presence: str, observed: Mapping[str, Any] | None
    ) -> bool:
        # Campos gerenciados do User: `lifecycle` e `platformAccess` (schemas/core/user/desired).
        if desired["lifecycle"] == "absent":
            return presence == "absent"
        return (
            presence == "present"
            and observed is not None
            and observed.get("platformAccess") == desired["platformAccess"]
        )
