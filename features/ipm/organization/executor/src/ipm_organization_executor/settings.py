"""Configuração do Executor de Organization (decisão 0015).

Ordem: variável de ambiente → default. Nome da variável:
`IPM_ORGANIZATION_EXECUTOR_<SEÇÃO>_<CAMPO>`, por exemplo `IPM_ORGANIZATION_EXECUTOR_NATS_URL`
(`docs/SCHEMA.md` §8.3). Sem default: a senha do NATS. O Executor
**não acessa o SSOT** e escreve só a organização no Zitadel.
"""

from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NatsSettings(_Section):
    url: str = "nats://broker.smarkee.internal:4222"
    user: str = "smarkee"
    password: SecretStr | None = None


class ZitadelSettings(_Section):
    base_url: str = "http://identity.smarkee.internal:8080"
    """Endereço da API do Zitadel na rede interna (não passa pelo gateway público)."""

    host_header: str = "ipm-dev.smarkee.com.br:8080"
    """`Host` enviado ao Zitadel: ele resolve a instância pelo domínio externo."""

    issuer: str = "http://ipm-dev.smarkee.com.br:8080"
    """Audience da assertion JWT da conta de serviço."""

    key_file: str = "/run/secrets/zitadel-key.json"
    """Chave JSON da conta `ipm-organization-executor` (papel de instância `IAM_ORG_MANAGER`)."""

    timeout_seconds: float = 10.0


class PartitionSettings(_Section):
    count: int = 4
    """Partições do Stream `ACTION` (bootstrap do broker): um consumer e um laço por partição."""


class HealthSettings(_Section):
    port: int = 8000
    """Porta das probes `/health/*` (decisão 0018)."""


class OrganizationExecutorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IPM_ORGANIZATION_EXECUTOR_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    nats: NatsSettings = NatsSettings()
    zitadel: ZitadelSettings = ZitadelSettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()


REQUIRED_SECRETS = ("IPM_ORGANIZATION_EXECUTOR_NATS_PASSWORD",)


def missing_required(settings: OrganizationExecutorSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    present = {"IPM_ORGANIZATION_EXECUTOR_NATS_PASSWORD": settings.nats.password is not None}
    return [name for name in REQUIRED_SECRETS if not present[name]]
