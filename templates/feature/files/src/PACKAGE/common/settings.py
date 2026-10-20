"""Seções e fontes de configuração comuns aos papéis (decisão 0063).

Cada papel declara a sua classe `RoleSettings` com o prefixo `@@UPPER@@_<PAPEL>_` e compõe as
seções abaixo. Precedência, da maior para a menor:

1. argumentos da linha de comando (só pelo entrypoint, via `load_settings`; nunca segredos);
2. variáveis de ambiente `<PREFIXO><SEÇÃO>_<CAMPO>` (`docs/SCHEMA.md` §8.3);
3. `config.toml`, tabela `[tool.@@DOTTED@@.<papel>.<seção>]`, no caminho de
   `SMARKEE_CONFIG_PATH` (padrão `config.toml`);
4. arquivos de segredo, um por variável completa, em `SMARKEE_SECRETS_DIR` (padrão
   `/run/secrets`);
5. o default do código: `localhost`, portas e timeouts padrão. Segredo nunca tem default.

Segredos não entram no `config.toml` nem na linha de comando (ela aparece em `ps`).
"""

import os
from collections.abc import Mapping, Sequence
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import (
    BaseSettings,
    CliApp,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

ENV_PREFIX = "@@UPPER@@_"
"""Prefixo das variáveis de ambiente da feature; cada papel acrescenta o seu nome."""

CONFIG_PATH_VARIABLE = "SMARKEE_CONFIG_PATH"
DEFAULT_CONFIG_PATH = "config.toml"
SECRETS_DIR_VARIABLE = "SMARKEE_SECRETS_DIR"
DEFAULT_SECRETS_DIR = "/run/secrets"
CONFIG_TABLE = ("tool", "@@MODULE@@", "@@TYPE@@")
"""Tabela do `config.toml` desta feature; cada papel acrescenta o seu nome."""

SECRET_FIELD_NAME = "password"  # noqa: S105 (nome de campo, não um segredo)
"""Nome do campo de segredo das seções; a linha de comando que o cita é recusada."""


def role_config(role: str) -> SettingsConfigDict:
    """Configuração do `BaseSettings` de um papel: variáveis `<ENV_PREFIX><PAPEL>_<SEÇÃO>_<CAMPO>`.

    `<ENV_PREFIX><PAPEL>_MESSAGING_URL` vira `messaging.url`: o delimitador separa somente a
    seção do campo.
    """
    return SettingsConfigDict(
        env_prefix=f"{ENV_PREFIX}{role.upper()}_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )


class ConfigTomlSource(TomlConfigSettingsSource):
    """Lê do `config.toml` somente a tabela do papel. Arquivo ausente equivale a tabela vazia."""

    def __init__(self, settings_cls: type[BaseSettings], table: tuple[str, ...]) -> None:
        self.table = table
        path = os.environ.get(CONFIG_PATH_VARIABLE, DEFAULT_CONFIG_PATH)
        super().__init__(settings_cls, toml_file=path)

    def _read_file(self, file_path: Path | Traversable) -> dict[str, Any]:
        data: Any = super()._read_file(file_path)
        for key in self.table:
            if not isinstance(data, dict):
                return {}
            data = cast("dict[str, Any]", data).get(key, {})
        return cast("dict[str, Any]", data) if isinstance(data, dict) else {}


class SecretFilesSource(EnvSettingsSource):
    """Lê segredos de arquivos: o nome do arquivo é o da variável de ambiente completa.

    Diretório ausente equivale a nenhum segredo (em dev os segredos vêm do ambiente).
    """

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        self.directory = Path(os.environ.get(SECRETS_DIR_VARIABLE, DEFAULT_SECRETS_DIR))
        super().__init__(settings_cls)

    def _load_env_vars(self) -> Mapping[str, str | None]:
        if not self.directory.is_dir():
            return {}
        return {
            path.name.lower(): path.read_text(encoding="utf-8").strip()
            for path in self.directory.iterdir()
            if path.is_file()
        }


class RoleSettings(BaseSettings):
    """Base da configuração de um papel: define as fontes e a precedência (ver o módulo)."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        prefix = str(settings_cls.model_config.get("env_prefix", ""))
        role = prefix.removeprefix(ENV_PREFIX).rstrip("_").lower()
        return (
            init_settings,
            env_settings,
            ConfigTomlSource(settings_cls, (*CONFIG_TABLE, role)),
            SecretFilesSource(settings_cls),
        )


def load_settings[S: BaseSettings](settings_type: type[S], cli_args: Sequence[str] = ()) -> S:
    """Monta a configuração do papel; `cli_args` é `sys.argv[1:]` do entrypoint (vazio nos testes).

    Segredo na linha de comando é recusado: ele apareceria em `ps` e no histórico do shell.
    """
    for argument in cli_args:
        if SECRET_FIELD_NAME in argument.lower():
            name = argument.split("=")[0]
            raise SystemExit(
                f"invalid command line: secrets are not accepted as arguments ({name})"
            )
    return CliApp.run(settings_type, cli_args=list(cli_args))


class Section(BaseModel):
    """Seção de configuração: campo desconhecido é rejeitado."""

    model_config = ConfigDict(extra="forbid")


class MessagingSettings(Section):
    url: str | None = None
    """Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`."""

    user: str | None = None
    """Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`."""

    password: SecretStr | None = None


class StateMessagingSettings(MessagingSettings):
    """NATS dos papéis com estado em memória e um consumer por instância (`NATS.md` §7.4)."""

    consumer_inactive_threshold_seconds: int = 300
    """Tempo sem uso após o qual o servidor remove o consumer da instância."""


class HealthSettings(Section):
    port: int = 8000
    """Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018)."""


class DatabaseSettings(Section):
    """Conexão com o SSOT."""

    host: str | None = None
    """Endereço do banco. Sem default: vem do ambiente ou do `config.toml`."""

    port: int | None = None
    name: str | None = None
    user: str | None = None
    """Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`."""

    password: SecretStr | None = None


def missing_variables(prefix: str, present: Mapping[str, bool]) -> list[str]:
    """Nomes completos das variáveis obrigatórias (sem default) que não foram informadas.

    `present` mapeia o sufixo da variável (por exemplo, `MESSAGING_PASSWORD`) para "foi informada".
    """
    return [f"{prefix}{name}" for name, informed in present.items() if not informed]
