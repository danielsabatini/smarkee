"""Tipos de recurso tratados pelo Manager: identificadores no SSOT e política de negócio."""

from dataclasses import dataclass

from psycopg import sql

from core.manager.policies import OrganizationPolicy, ResourcePolicy, UserPolicy

MODULE = "core"


@dataclass(frozen=True, slots=True)
class ResourceKind:
    resource_type: str
    table: sql.Identifier
    operation_table: sql.Identifier
    outbox_table: sql.Identifier
    policy: ResourcePolicy

    @property
    def requested_filter_subject(self) -> str:
        """Filtro do consumer de `requested` do tipo (`docs/NATS.md` §7)."""
        return f"api.requested.{MODULE}.{self.resource_type}.>"


ORGANIZATION = ResourceKind(
    resource_type="organization",
    table=sql.Identifier("core", "organization"),
    operation_table=sql.Identifier("core", "organization_operation"),
    outbox_table=sql.Identifier("core", "organization_outbox"),
    policy=OrganizationPolicy(),
)

# `user` é palavra reservada do PostgreSQL: sql.Identifier cita o nome (core."user").
USER = ResourceKind(
    resource_type="user",
    table=sql.Identifier("core", "user"),
    operation_table=sql.Identifier("core", "user_operation"),
    outbox_table=sql.Identifier("core", "user_outbox"),
    policy=UserPolicy(),
)

KINDS_BY_RESOURCE_TYPE = {kind.resource_type: kind for kind in (ORGANIZATION, USER)}
