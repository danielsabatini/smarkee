"""Configuração do CLI.

Precedência, da maior para a menor:

1. parâmetro da linha de comando (somente os informados explicitamente);
2. variável de ambiente (`SK_<SEÇÃO>_<CAMPO>`, por exemplo `SK_AUTH_CLIENT_ID`);
3. arquivo de configuração TOML (`$XDG_CONFIG_HOME/sk/config.toml`, padrão
   `~/.config/sk/config.toml`), com uma tabela por seção (por exemplo `[auth]`);
4. valor padrão do campo.

As fontes 1, 2 e 4 são o comportamento padrão do pydantic-settings (argumentos de
inicialização, ambiente e default). O arquivo TOML é acrescentado entre o ambiente e o
default por `settings_customise_sources`. Arquivos `.env` e diretórios de secrets não são
lidos.

Grafia dos nomes por meio (`docs/SCHEMA.md`, *Grafia dos nomes por meio*): os campos são
`snake_case` no código, as chaves do arquivo são camelCase (`clientId`), as variáveis são
`SK_AUTH_CLIENT_ID`. A conversão do arquivo é feita só pela
fonte TOML: uma chave fora do camelCase (por exemplo `client_id`) é rejeitada.

O arquivo de configuração guarda configuração, e não credenciais: os tokens ficam no
arquivo de credenciais (`sk.identity.credentials`).
"""

import json
import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from sk.defaults import (
    PRD_API_URL,
    PRD_CLIENT_ID,
    PRD_CORE_PROJECT_ID,
    PRD_IPM_PROJECT_ID,
    PRD_ISSUER,
    PRD_SUM_PROJECT_ID,
)

CONFIG_DIRECTORY_NAME = "sk"
CONFIG_FILE_NAME = "config.toml"


class ConfigurationError(Exception):
    """Arquivo de configuração ilegível ou com chave inválida."""


def config_directory(environment: Mapping[str, str] = os.environ) -> Path:
    """Diretório de configuração do sk, respeitando `XDG_CONFIG_HOME`."""
    config_home = environment.get("XDG_CONFIG_HOME")
    base_directory = Path(config_home) if config_home else Path.home() / ".config"
    return base_directory / CONFIG_DIRECTORY_NAME


def config_file_path(environment: Mapping[str, str] = os.environ) -> Path:
    return config_directory(environment) / CONFIG_FILE_NAME


class AuthSettings(BaseModel):
    """Seção `auth`: provedor de identidade usado por `sk auth`."""

    model_config = ConfigDict(extra="forbid")

    issuer: str = PRD_ISSUER
    """URL do issuer OIDC, acessado pelo gateway."""

    client_id: str = PRD_CLIENT_ID
    """Client ID da aplicação nativa do sk no provedor."""

    allow_insecure_http: bool = False
    """Aceita issuer `http`. Somente em desenvolvimento."""


def _model_type(field: FieldInfo) -> type[BaseModel] | None:
    annotation = field.annotation
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _file_keys_to_field_names(
    document: Mapping[str, Any], model: type[BaseModel], *, path: Path, location: str
) -> dict[str, Any]:
    """Converte as chaves camelCase do arquivo para os nomes dos campos do modelo."""
    field_names_by_key = {to_camel(name): name for name in model.model_fields}
    converted: dict[str, Any] = {}
    for key, value in document.items():
        qualified_key = f"{location}{key}"
        field_name = field_names_by_key.get(key)
        if field_name is None:
            raise ConfigurationError(
                f"unknown key in {path}: {qualified_key}. The file keys are "
                f"camelCase: {', '.join(sorted(field_names_by_key))}."
            )
        nested_model = _model_type(model.model_fields[field_name])
        if nested_model is not None:
            if not isinstance(value, dict):
                raise ConfigurationError(f"{qualified_key} in {path} must be a TOML table.")
            value = _file_keys_to_field_names(
                cast(dict[str, Any], value), nested_model, path=path, location=f"{qualified_key}."
            )
        converted[field_name] = value
    return converted


def read_config_document(path: Path) -> dict[str, Any]:
    """Lê o TOML do arquivo, com as chaves como estão escritas. Arquivo ausente devolve `{}`."""
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as error:
        raise ConfigurationError(f"could not read {path}: {error.strerror}") from error
    try:
        return tomllib.loads(content)
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"invalid TOML in {path}: {error}") from error


def convert_file_document(
    settings_cls: type[BaseSettings], document: Mapping[str, Any], *, path: Path | None = None
) -> dict[str, Any]:
    """Converte um documento do arquivo (chaves camelCase) para os nomes dos campos.

    Chave desconhecida ou fora do camelCase levanta `ConfigurationError`.
    """
    return _file_keys_to_field_names(
        document, settings_cls, path=path or config_file_path(), location=""
    )


class CamelCaseTomlSettingsSource(PydanticBaseSettingsSource):
    """Fonte do arquivo `config.toml`, cujas chaves são camelCase."""

    def __init__(self, settings_cls: type[BaseSettings], toml_file: Path) -> None:
        super().__init__(settings_cls)
        self._toml_file = toml_file

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        # Não utilizado: __call__ devolve o documento inteiro já convertido.
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        return convert_file_document(self.settings_cls, read_config_document(self._toml_file))


class ApiSettings(BaseModel):
    """Seção `api`: a API da plataforma, pelo gateway, usada por todos os módulos."""

    model_config = ConfigDict(extra="forbid")

    url: str = PRD_API_URL
    """URL base da API (por exemplo, `https://api.exemplo`)."""

    allow_insecure_http: bool = False
    """Aceita `url` em `http`. Somente em desenvolvimento."""


class CoreSettings(BaseModel):
    """Seção `core`: o módulo core (`sk register`)."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = PRD_CORE_PROJECT_ID
    """ID do projeto de roles do core (`roles-core`): audience dos tokens do Receiver do User."""


class SumSettings(BaseModel):
    """Seção `sum`: Service Usage Manager, usado por `sk sum`."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = PRD_SUM_PROJECT_ID
    """ID do projeto de roles do SUM (`roles-sum`): audience dos tokens do Receiver do SUM."""


class IpmSettings(BaseModel):
    """Seção `ipm`: módulo de Organizations, usado por `sk ipm`."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = PRD_IPM_PROJECT_ID
    """ID do projeto de roles do ipm (`roles-ipm`): audience dos tokens do Receiver do ipm."""


class SkSettings(BaseSettings):
    """Configuração consolidada do sk."""

    model_config = SettingsConfigDict(
        env_prefix="SK_",
        # SK_AUTH_CLIENT_ID → auth.client_id: separa somente a seção do campo.
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    auth: AuthSettings = AuthSettings()
    api: ApiSettings = ApiSettings()
    core: CoreSettings = CoreSettings()
    sum: SumSettings = SumSettings()
    ipm: IpmSettings = IpmSettings()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # O caminho é resolvido a cada carga, para respeitar o XDG_CONFIG_HOME vigente.
        return (
            init_settings,
            env_settings,
            CamelCaseTomlSettingsSource(settings_cls, toml_file=config_file_path()),
        )


def _render_toml_value(value: str | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    # Uma string JSON é uma string básica TOML válida (mesmas regras de escape).
    return json.dumps(value, ensure_ascii=False)


def render_section(section_name: str, settings: BaseModel) -> str:
    """Gera a tabela TOML de uma seção, com chaves camelCase, só dos campos informados.

    Um campo que ficou no padrão não vai para o arquivo: o arquivo guarda só sobrescritas.
    """
    lines = [f"[{section_name}]"]
    for field_name, value in settings.model_dump(exclude_unset=True).items():
        if isinstance(value, str | bool):
            lines.append(f"{to_camel(field_name)} = {_render_toml_value(value)}")
    return "\n".join(lines) + "\n"
