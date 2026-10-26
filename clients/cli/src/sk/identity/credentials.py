"""Armazenamento local das credenciais do CLI.

As credenciais ficam em `$XDG_CONFIG_HOME/sk/credentials.json` (padrão:
`~/.config/sk/credentials.json`), com permissão 0600 no arquivo e 0700 no diretório
criado. O arquivo guarda uma única sessão da plataforma: um novo login a substitui.

A gravação é atômica (`sk.files.write_private_file`).
"""

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from sk.files import write_private_file
from sk.settings import config_directory

CREDENTIALS_FILE_NAME = "credentials.json"


class CredentialsError(Exception):
    """Falha ao ler ou gravar o arquivo de credenciais. A mensagem não contém tokens."""


class CredentialsMissingError(CredentialsError):
    """Não há arquivo de credenciais: a pessoa ainda não entrou na plataforma."""


@dataclass(frozen=True, slots=True)
class StoredCredentials:
    """Tokens obtidos no login, com o issuer e o cliente que os emitiram."""

    issuer: str
    client_id: str
    token_type: str
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str | None
    id_token: str | None
    scope: str | None
    obtained_at: datetime
    key_file: str | None = None

    def to_json_object(self) -> dict[str, str | None]:
        payload: dict[str, str | None] = {
            "issuer": self.issuer,
            "clientId": self.client_id,
            "tokenType": self.token_type,
            "accessToken": self.access_token,
            "accessTokenExpiresAt": self.access_token_expires_at.isoformat(),
            "refreshToken": self.refresh_token,
            "idToken": self.id_token,
            "scope": self.scope,
            "obtainedAt": self.obtained_at.isoformat(),
        }
        if self.key_file is not None:
            payload["keyFile"] = self.key_file
        return payload


def default_credentials_path(environment: Mapping[str, str] = os.environ) -> Path:
    """Caminho do arquivo de credenciais, no diretório de configuração do sk."""
    return config_directory(environment) / CREDENTIALS_FILE_NAME


def _text(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(key)
    return value


def _optional_text(data: Mapping[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(key)
    return value


def load_credentials(path: Path) -> StoredCredentials:
    """Lê as credenciais gravadas por `save_credentials`.

    Sem arquivo, levanta `CredentialsMissingError`. Arquivo ilegível ou fora do formato levanta
    `CredentialsError` sem o conteúdo, para não expor tokens na mensagem.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise CredentialsMissingError(f"there are no credentials at {path}") from error
    except OSError as error:
        raise CredentialsError(f"could not read {path}: {error.strerror}") from error
    try:
        payload: object = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("raiz")
        data = cast(dict[str, object], payload)
        client_id = (
            _optional_text(data, "clientId") if "keyFile" in data else _text(data, "clientId")
        )
        return StoredCredentials(
            issuer=_text(data, "issuer"),
            client_id=client_id or "",
            token_type=_text(data, "tokenType"),
            access_token=_text(data, "accessToken"),
            access_token_expires_at=datetime.fromisoformat(_text(data, "accessTokenExpiresAt")),
            refresh_token=_optional_text(data, "refreshToken"),
            id_token=_optional_text(data, "idToken"),
            scope=_optional_text(data, "scope"),
            obtained_at=datetime.fromisoformat(_text(data, "obtainedAt")),
            key_file=_optional_text(data, "keyFile"),
        )
    except (ValueError, TypeError) as error:
        raise CredentialsError(f"invalid credentials file: {path}") from error


def save_credentials(path: Path, credentials: StoredCredentials) -> None:
    """Grava as credenciais, substituindo as anteriores."""
    try:
        write_private_file(path, json.dumps(credentials.to_json_object(), indent=2) + "\n")
    except OSError as error:
        raise CredentialsError(f"could not write {path}: {error.strerror}") from error
