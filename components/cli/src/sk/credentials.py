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

from sk.files import write_private_file
from sk.settings import config_directory

CREDENTIALS_FILE_NAME = "credentials.json"


class CredentialsError(Exception):
    """Falha ao gravar o arquivo de credenciais. A mensagem não contém tokens."""


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

    def to_json_object(self) -> dict[str, str | None]:
        return {
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


def default_credentials_path(environment: Mapping[str, str] = os.environ) -> Path:
    """Caminho do arquivo de credenciais, no diretório de configuração do sk."""
    return config_directory(environment) / CREDENTIALS_FILE_NAME


def save_credentials(path: Path, credentials: StoredCredentials) -> None:
    """Grava as credenciais, substituindo as anteriores."""
    try:
        write_private_file(path, json.dumps(credentials.to_json_object(), indent=2) + "\n")
    except OSError as error:
        raise CredentialsError(f"não foi possível gravar {path}: {error.strerror}") from error
