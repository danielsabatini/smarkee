"""Tipo de recurso tratado pelo Manager: identificadores no SSOT e política de negócio."""

from dataclasses import dataclass

from psycopg import sql

from ipm_organization_manager.policies import OrganizationPolicy, ResourcePolicy

MODULE = "ipm"


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
        return f"receiver.requested.{MODULE}.{self.resource_type}.>"


ORGANIZATION = ResourceKind(
    resource_type="organization",
    table=sql.Identifier("ipm", "organization"),
    operation_table=sql.Identifier("ipm", "organization_operation"),
    outbox_table=sql.Identifier("ipm", "organization_outbox"),
    policy=OrganizationPolicy(),
)
