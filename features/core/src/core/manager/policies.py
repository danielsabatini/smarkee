"""Regras de negócio por tipo de recurso, aplicadas pelo Manager.

Cada política interpreta o `requested` do seu tipo, calcula o novo `desired` e confere as
regras que dependem do estado do SSOT (unicidade e cota). O `desired` guardado no SSOT tem o
formato do contrato (camelCase) e contém a especificação **e** o `lifecycle`; a
`reconciliation` é um campo à parte, porque mudá-la não incrementa a geração
(`docs/SCHEMA.md` §7.1).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from psycopg import AsyncConnection, sql
from pydantic import ValidationError

from core.contracts import generated
from core.contracts.base import ContractModel
from core.manager.errors import PermanentMessageError
from core.manager.outcome import RejectionReason

Operation = Literal["create", "update", "delete"]

# Nomes que nenhuma Organization de cliente pode usar (decisão 0010): organizações de sistema
# do Zitadel e termos que se confundiriam com a plataforma. Lista da plataforma, em código por
# enquanto; vira configuração quando houver necessidade.
RESERVED_ORGANIZATION_NAMES = frozenset(
    {"core", "smarkee", "platform", "system", "admin", "zitadel"}
)


@dataclass(frozen=True, slots=True)
class Request:
    """Conteúdo de um `requested`, já validado, independente do tipo de recurso."""

    operation: Operation
    operation_id: str
    request_digest: str
    resource_version: int | None = None
    specification: Mapping[str, Any] | None = None
    reconciliation: str | None = None
    owner_quota_limit: int | None = None


class ResourcePolicy(Protocol):
    def parse(self, operation: str, data: Mapping[str, Any]) -> Request: ...

    def desired_for_create(self, request: Request, requested_by: str) -> dict[str, Any]: ...

    def desired_for_update(
        self, current: Mapping[str, Any], request: Request
    ) -> dict[str, Any]: ...

    def desired_for_delete(self, current: Mapping[str, Any]) -> dict[str, Any]: ...

    async def check(
        self,
        connection: AsyncConnection[Any],
        table: sql.Identifier,
        *,
        request: Request,
        requested_by: str,
        resource_id: str,
        desired: Mapping[str, Any],
        current: Mapping[str, Any] | None,
    ) -> RejectionReason | None: ...

    def message_data(self, desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]: ...


async def advisory_transaction_lock(connection: AsyncConnection[Any], key: str) -> None:
    """Serializa transações que concorrem pela mesma regra de unicidade ou de cota."""
    await connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (key,))


async def _exists_with_value(
    connection: AsyncConnection[Any],
    table: sql.Identifier,
    *,
    field: str,
    value: str,
    excluding_resource_id: str,
) -> bool:
    query = sql.SQL(
        "SELECT 1 FROM {table} WHERE desired ->> {field} = %s AND resource_id <> %s LIMIT 1"
    ).format(table=table, field=sql.Literal(field))
    cursor = await connection.execute(query, (value, excluding_resource_id))
    return await cursor.fetchone() is not None


def _validated[M: ContractModel](model: type[M], data: Mapping[str, Any], *, label: str) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as error:
        fields = ", ".join(".".join(str(part) for part in item["loc"]) for item in error.errors())
        raise PermanentMessageError(f"{label} inválido nos campos: {fields}") from None


class OrganizationPolicy:
    """Organization: nome único e não reservado, dono e cota por dono (decisão 0010)."""

    def parse(self, operation: str, data: Mapping[str, Any]) -> Request:
        match operation:
            case "create":
                create = _validated(
                    generated.OrganizationRequestedCreateData, data, label="requested/create"
                )
                return Request(
                    "create",
                    create.operation_id,
                    create.request_digest,
                    specification={
                        "name": create.specification.name,
                        "platformAccess": create.specification.platform_access.value,
                    },
                    owner_quota_limit=create.owner_quota_limit,
                )
            case "update":
                update = _validated(
                    generated.OrganizationRequestedUpdateData, data, label="requested/update"
                )
                specification: dict[str, Any] = {}
                if update.specification is not None:
                    if update.specification.name is not None:
                        specification["name"] = update.specification.name
                    if update.specification.platform_access is not None:
                        specification["platformAccess"] = update.specification.platform_access.value
                return Request(
                    "update",
                    update.operation_id,
                    update.request_digest,
                    resource_version=_parse_resource_version(update.resource_version),
                    specification=specification,
                    reconciliation=update.reconciliation.value if update.reconciliation else None,
                )
            case "delete":
                delete = _validated(
                    generated.OrganizationRequestedDeleteData, data, label="requested/delete"
                )
                return Request(
                    "delete",
                    delete.operation_id,
                    delete.request_digest,
                    resource_version=_parse_resource_version(delete.resource_version),
                )
            case _:
                raise PermanentMessageError(
                    f"operação não suportada para organization: {operation}"
                )

    def desired_for_create(self, request: Request, requested_by: str) -> dict[str, Any]:
        assert request.specification is not None  # noqa: S101 (invariante de parse)
        return {
            "lifecycle": "present",
            "name": request.specification["name"],
            "platformAccess": request.specification["platformAccess"],
            "ownerUserId": requested_by,
        }

    def desired_for_update(self, current: Mapping[str, Any], request: Request) -> dict[str, Any]:
        return {**current, **(request.specification or {})}

    def desired_for_delete(self, current: Mapping[str, Any]) -> dict[str, Any]:
        return {**current, "lifecycle": "absent"}

    async def check(
        self,
        connection: AsyncConnection[Any],
        table: sql.Identifier,
        *,
        request: Request,
        requested_by: str,
        resource_id: str,
        desired: Mapping[str, Any],
        current: Mapping[str, Any] | None,
    ) -> RejectionReason | None:
        if desired["lifecycle"] != "present":
            return None
        name: str = desired["name"]
        if name in RESERVED_ORGANIZATION_NAMES:
            return RejectionReason.VALIDATION
        if current is None or current.get("name") != name:
            await advisory_transaction_lock(connection, f"core.organization.name:{name}")
            if await _exists_with_value(
                connection, table, field="name", value=name, excluding_resource_id=resource_id
            ):
                return RejectionReason.VALIDATION
        if request.operation == "create" and request.owner_quota_limit is not None:
            await advisory_transaction_lock(connection, f"core.organization.owner:{requested_by}")
            query = sql.SQL(
                "SELECT count(*) FROM {table} WHERE desired ->> 'ownerUserId' = %s"
            ).format(table=table)
            cursor = await connection.execute(query, (requested_by,))
            row = await cursor.fetchone()
            if row is not None and row[0] >= request.owner_quota_limit:
                return RejectionReason.VALIDATION
        return None

    def message_data(self, desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
        model = generated.OrganizationDesiredData.model_validate(
            {**desired, "reconciliation": reconciliation}
        )
        return model.model_dump(mode="json", exclude_none=True)


def normalize_email(email: str) -> str:
    """Regra de normalização `lowercase` (com `trim`) do e-mail, também o nome de login."""
    return email.strip().lower()


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

    async def check(
        self,
        connection: AsyncConnection[Any],
        table: sql.Identifier,
        *,
        request: Request,
        requested_by: str,
        resource_id: str,
        desired: Mapping[str, Any],
        current: Mapping[str, Any] | None,
    ) -> RejectionReason | None:
        if desired["lifecycle"] != "present":
            return None
        email: str = desired["email"]
        await advisory_transaction_lock(connection, f"core.user.email:{email}")
        if await _exists_with_value(
            connection, table, field="email", value=email, excluding_resource_id=resource_id
        ):
            return RejectionReason.VALIDATION
        return None

    def message_data(self, desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
        model = generated.UserDesiredData.model_validate(
            {**desired, "reconciliation": reconciliation}
        )
        return model.model_dump(mode="json", exclude_none=True)


def _parse_resource_version(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise PermanentMessageError("resourceVersion não numérico") from None
