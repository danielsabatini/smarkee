"""Sessão do sk: devolve um access token válido, renovando-o pelo refresh token se preciso.

O access token tem validade curta (decisão 0033): quando está para vencer, o sk troca o refresh
token por um novo e regrava as credenciais, sem pedir login de novo. Sem refresh token, ou se o
provedor o recusar, a pessoa precisa rodar `sk auth login`. A mensagem de erro nunca contém tokens.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sk.identity.credentials import (
    CredentialsError,
    CredentialsMissingError,
    StoredCredentials,
    load_credentials,
    save_credentials,
)
from sk.identity.oidc import OidcError, fetch_provider_metadata, refresh_access_token

# Renova antes do vencimento real, para o pedido seguinte não chegar com o token já expirado.
RENEWAL_MARGIN = timedelta(seconds=60)


class SessionError(Exception):
    """Não há sessão utilizável. A mensagem diz o que a pessoa deve fazer."""


def current_access_token(
    credentials_path: Path, *, allow_insecure_http: bool, now: datetime | None = None
) -> str:
    """Access token válido das credenciais salvas (renovado se estiver para vencer)."""
    moment = now or datetime.now(UTC)
    try:
        credentials = load_credentials(credentials_path)
    except CredentialsMissingError as error:
        raise SessionError("There is no session. Run `sk auth login`.") from error
    except CredentialsError as error:
        raise SessionError(f"{error}. Run `sk auth login` again.") from error
    if credentials.access_token_expires_at - RENEWAL_MARGIN > moment:
        return credentials.access_token
    return _renew(
        credentials, credentials_path, allow_insecure_http=allow_insecure_http, now=moment
    )


def renew_session(
    credentials_path: Path, *, allow_insecure_http: bool, now: datetime | None = None
) -> datetime:
    """Renova a sessão agora, mesmo com o acesso ainda válido, e devolve o novo vencimento.

    O token só traz as roles que existiam quando foi emitido: depois de habilitar ou desabilitar
    de serviço, renovar é o que faz o token refletir as roles novas.
    """
    moment = now or datetime.now(UTC)
    try:
        credentials = load_credentials(credentials_path)
    except CredentialsMissingError as error:
        raise SessionError("There is no session. Run `sk auth login`.") from error
    except CredentialsError as error:
        raise SessionError(f"{error}. Run `sk auth login` again.") from error
    _renew(credentials, credentials_path, allow_insecure_http=allow_insecure_http, now=moment)
    return load_credentials(credentials_path).access_token_expires_at


def _renew(
    credentials: StoredCredentials,
    credentials_path: Path,
    *,
    allow_insecure_http: bool,
    now: datetime,
) -> str:
    if credentials.refresh_token is None:
        raise SessionError(
            "The session expired and there is no refresh token. Run `sk auth login`."
        )
    try:
        metadata = fetch_provider_metadata(
            credentials.issuer, allow_insecure_http=allow_insecure_http
        )
        renewed = refresh_access_token(
            metadata, client_id=credentials.client_id, refresh_token=credentials.refresh_token
        )
    except OidcError as error:
        raise SessionError(
            f"Could not renew the session ({error}). Run `sk auth login`."
        ) from error
    updated = replace(
        credentials,
        access_token=renewed.access_token,
        access_token_expires_at=now + timedelta(seconds=renewed.expires_in_seconds),
        # Refresh token novo substitui o antigo; sem ele, o antigo continua válido.
        refresh_token=renewed.refresh_token or credentials.refresh_token,
        id_token=renewed.id_token or credentials.id_token,
        scope=renewed.scope or credentials.scope,
        obtained_at=now,
    )
    try:
        save_credentials(credentials_path, updated)
    except CredentialsError as error:
        raise SessionError(f"{error}. Run `sk auth login` again.") from error
    return updated.access_token
