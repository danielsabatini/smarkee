"""Configuração do Executor de User (decisão 0015).

Ordem: variável de ambiente → default. Nome da variável:
`CORE_USER_EXECUTOR_<SEÇÃO>_<CAMPO>`, por exemplo `CORE_USER_EXECUTOR_NATS_URL`
(`docs/SCHEMA.md` §8.3). Sem default: a senha do NATS e os identificadores do Zitadel. O Executor
**não acessa o SSOT** e é a única identidade com escrita no Zitadel.
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
    """Chave JSON da conta de serviço `core-user-executor` (papel `ORG_USER_MANAGER`)."""

    organization_id: str | None = None
    """ID da organização `core`, onde os usuários são criados. Sem default."""

    project_id: str | None = None
    """ID do projeto `smarkee`, onde o usuário recebe as roles. Sem default."""

    granted_roles: tuple[str, ...] = (
        "organization.create",
        "organization.get",
        "organization.list",
        "organization.update",
        "organization.delete",
        "user.get",
        "user.delete",
    )
    """Roles de ação do usuário cadastrado (`platformAccess = granted`, decisão 0014)."""

    timeout_seconds: float = 10.0


class PartitionSettings(_Section):
    count: int = 4
    """Partições do Stream `ACTION` (bootstrap do broker): um consumer e um laço por partição."""


class HealthSettings(_Section):
    port: int = 8000
    """Porta das probes `/health/*` (decisão 0018)."""


class UserExecutorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CORE_USER_EXECUTOR_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    nats: NatsSettings = NatsSettings()
    zitadel: ZitadelSettings = ZitadelSettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()


REQUIRED_SECRETS = (
    "CORE_USER_EXECUTOR_NATS_PASSWORD",
    "CORE_USER_EXECUTOR_ZITADEL_ORGANIZATION_ID",
    "CORE_USER_EXECUTOR_ZITADEL_PROJECT_ID",
)


def missing_required(settings: UserExecutorSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    present = {
        "CORE_USER_EXECUTOR_NATS_PASSWORD": settings.nats.password is not None,
        "CORE_USER_EXECUTOR_ZITADEL_ORGANIZATION_ID": bool(settings.zitadel.organization_id),
        "CORE_USER_EXECUTOR_ZITADEL_PROJECT_ID": bool(settings.zitadel.project_id),
    }
    return [name for name in REQUIRED_SECRETS if not present[name]]
