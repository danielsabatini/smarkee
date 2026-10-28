"""Modelos e tipos para a recuperação e republicação de estados desired."""

import uuid
from dataclasses import dataclass
from typing import Any

# Namespace determinístico UUID para IDs de mensagem de republish
REPUBLISH_NAMESPACE = uuid.UUID("0199c8a4-0000-7000-8000-000000000000")


def deterministic_message_id(
    module: str, resource_type: str, resource_id: str, generation: int
) -> str:
    """Gera um message_id determinístico para idempotência em outbox e Nats-Msg-Id."""
    name = f"{module}:{resource_type}:{resource_id}:{generation}"
    return str(uuid.uuid5(REPUBLISH_NAMESPACE, name))


@dataclass(frozen=True, slots=True)
class Kind:
    """Definição de uma feature/recurso no SSOT."""

    module: str
    resource_type: str
    table: str
    outbox_table: str
    manager_role: str


ACCOUNTS = Kind("core", "account", "core.account", "core.account_outbox", "core_account_api_login")
SERVICES = Kind("sum", "service", "sum.service", "sum.service_outbox", "sum_service_api_login")
ORGANIZATIONS = Kind(
    "ipm",
    "organization",
    "ipm.organization",
    "ipm.organization_outbox",
    "ipm_organization_manager_login",
)
USERS = Kind("ipm", "user", "ipm.user", "ipm.user_outbox", "ipm_user_manager_login")
BILLING_ACCOUNTS = Kind(
    "bsm", "account", "bsm.account", "bsm.account_outbox", "bsm_account_manager_login"
)
PERMISSIONS = Kind(
    "ipm",
    "permission",
    "ipm.permission",
    "ipm.permission_outbox",
    "ipm_permission_api_login",
)
ROLES = Kind("ipm", "role", "ipm.role", "ipm.role_outbox", "ipm_role_api_login")
GROUPS = Kind("ipm", "group", "ipm.group", "ipm.group_outbox", "ipm_group_api_login")
SERVICEACCOUNTS = Kind(
    "ipm",
    "serviceaccount",
    "ipm.serviceaccount",
    "ipm.serviceaccount_outbox",
    "ipm_serviceaccount_api_login",
)

ALL_KINDS: tuple[Kind, ...] = (
    ACCOUNTS,
    SERVICES,
    ORGANIZATIONS,
    USERS,
    BILLING_ACCOUNTS,
    PERMISSIONS,
    ROLES,
    GROUPS,
    SERVICEACCOUNTS,
)


@dataclass(frozen=True, slots=True)
class DesiredRecord:
    """Registro de um recurso no SSOT pronto para publicação."""

    module: str
    resource_type: str
    resource_id: str
    desired_generation: int
    lifecycle: str
    reconciliation: str
    desired: dict[str, Any]
    message_id: str
    subject: str
    envelope: dict[str, Any]
