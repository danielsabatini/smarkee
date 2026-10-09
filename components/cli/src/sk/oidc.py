"""Cliente OIDC do CLI.

Implementa o fluxo Authorization Code com PKCE (RFC 7636) e redirect em loopback
(RFC 8252, seção 7.3) somente com a biblioteca padrão. O CLI é um cliente público:
não possui segredo e prova a autoria da requisição pelo `code_verifier`.

O CLI não interpreta as claims do ID token (não valida a assinatura localmente); a
identidade exibida vem do endpoint userinfo, consultado com o access token recebido.
Por isso o `nonce` não é utilizado.

Nenhuma mensagem de erro deste módulo contém tokens, códigos de autorização ou o
`code_verifier`.
"""

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import TracebackType
from typing import Self, cast

CALLBACK_PATH = "/callback"
LOOPBACK_HOST = "127.0.0.1"
HTTP_TIMEOUT_SECONDS = 30
CODE_CHALLENGE_METHOD = "S256"

CALLBACK_PAGE = (
    '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>sk</title></head>'
    "<body><p>Retorno do login recebido. Você já pode fechar esta janela e voltar ao terminal.</p>"
    "</body></html>"
).encode()


class OidcError(Exception):
    """Falha em uma etapa do fluxo OIDC. A mensagem identifica a etapa e não contém segredos."""


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    """Endpoints do provedor, obtidos do documento de discovery."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str


@dataclass(frozen=True, slots=True)
class PkcePair:
    """Par PKCE: o verificador fica no CLI; o desafio vai na URL de autorização."""

    code_verifier: str
    code_challenge: str


@dataclass(frozen=True, slots=True)
class TokenResponse:
    """Resposta do token endpoint."""

    access_token: str
    token_type: str
    expires_in_seconds: int
    refresh_token: str | None
    id_token: str | None
    scope: str | None


def compute_code_challenge(code_verifier: str) -> str:
    """Calcula o `code_challenge` S256: BASE64URL(SHA256(verifier)), sem padding."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def create_pkce_pair() -> PkcePair:
    """Gera um par PKCE novo, de uso único."""
    # 64 bytes aleatórios geram 86 caracteres, dentro do intervalo de 43 a 128 da RFC 7636.
    code_verifier = secrets.token_urlsafe(64)
    return PkcePair(code_verifier, compute_code_challenge(code_verifier))


def ensure_secure_url(url: str, *, allow_insecure_http: bool) -> None:
    """Aceita somente HTTPS, ou HTTP quando permitido explicitamente (desenvolvimento)."""
    scheme = urllib.parse.urlsplit(url).scheme
    if scheme == "https" or (scheme == "http" and allow_insecure_http):
        return
    if scheme == "http":
        raise OidcError(
            f"URL sem TLS recusada: {url}. Use HTTPS ou permita HTTP explicitamente "
            "(somente em desenvolvimento)."
        )
    raise OidcError(f"Esquema de URL não suportado: {url}")


def _describe_provider_error(error: urllib.error.HTTPError) -> str:
    """Extrai `error` e `error_description` (RFC 6749, seção 5.2) da resposta, se houver."""
    try:
        payload = json.loads(error.read())
    except ValueError, OSError:
        return ""
    if not isinstance(payload, dict):
        return ""
    fields = cast(dict[str, object], payload)
    details = [
        value for key in ("error", "error_description") if isinstance(value := fields.get(key), str)
    ]
    return f" ({': '.join(details)})" if details else ""


def _request_json(request: urllib.request.Request, *, operation: str) -> dict[str, object]:
    """Executa a requisição e devolve o corpo JSON (objeto)."""
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:  # noqa: S310 (esquema validado por ensure_secure_url)
            body = cast(bytes, response.read())
    except urllib.error.HTTPError as error:
        raise OidcError(
            f"{operation}: o provedor respondeu HTTP {error.code}{_describe_provider_error(error)}"
        ) from error
    except urllib.error.URLError as error:
        raise OidcError(
            f"{operation}: falha de conexão com {request.full_url} ({error.reason})"
        ) from error
    except TimeoutError as error:
        raise OidcError(f"{operation}: tempo esgotado aguardando {request.full_url}") from error
    try:
        payload = json.loads(body)
    except ValueError as error:
        raise OidcError(f"{operation}: a resposta não é JSON válido") from error
    if not isinstance(payload, dict):
        raise OidcError(f"{operation}: a resposta não é um objeto JSON")
    return cast(dict[str, object], payload)


def _require_string(payload: Mapping[str, object], key: str, *, operation: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise OidcError(f"{operation}: campo obrigatório ausente ou inválido: {key}")
    return value


def _optional_string(payload: Mapping[str, object], key: str, *, operation: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise OidcError(f"{operation}: campo inválido: {key}")
    return value


def fetch_provider_metadata(issuer: str, *, allow_insecure_http: bool) -> ProviderMetadata:
    """Obtém e valida o documento de discovery (OpenID Connect Discovery 1.0)."""
    operation = "discovery OIDC"
    ensure_secure_url(issuer, allow_insecure_http=allow_insecure_http)
    configured_issuer = issuer.rstrip("/")
    request = urllib.request.Request(  # noqa: S310 (esquema validado por ensure_secure_url)
        f"{configured_issuer}/.well-known/openid-configuration",
        headers={"Accept": "application/json"},
    )
    payload = _request_json(request, operation=operation)

    advertised_issuer = _require_string(payload, "issuer", operation=operation)
    if advertised_issuer.rstrip("/") != configured_issuer:
        raise OidcError(
            f"{operation}: o issuer anunciado ({advertised_issuer}) difere do configurado "
            f"({configured_issuer})"
        )
    challenge_methods = payload.get("code_challenge_methods_supported")
    if isinstance(challenge_methods, list) and CODE_CHALLENGE_METHOD not in challenge_methods:
        raise OidcError(f"{operation}: o provedor não anuncia PKCE {CODE_CHALLENGE_METHOD}")

    metadata = ProviderMetadata(
        issuer=advertised_issuer,
        authorization_endpoint=_require_string(
            payload, "authorization_endpoint", operation=operation
        ),
        token_endpoint=_require_string(payload, "token_endpoint", operation=operation),
        userinfo_endpoint=_require_string(payload, "userinfo_endpoint", operation=operation),
    )
    for endpoint in (
        metadata.authorization_endpoint,
        metadata.token_endpoint,
        metadata.userinfo_endpoint,
    ):
        ensure_secure_url(endpoint, allow_insecure_http=allow_insecure_http)
    return metadata


def build_authorization_url(
    metadata: ProviderMetadata,
    *,
    client_id: str,
    redirect_uri: str,
    scopes: Sequence[str],
    state: str,
    code_challenge: str,
) -> str:
    """Monta a URL do authorization endpoint para o navegador."""
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": CODE_CHALLENGE_METHOD,
        },
        quote_via=urllib.parse.quote,
    )
    separator = "&" if "?" in metadata.authorization_endpoint else "?"
    return f"{metadata.authorization_endpoint}{separator}{query}"


class _CallbackServer(HTTPServer):
    """Servidor que guarda os parâmetros do primeiro retorno recebido em CALLBACK_PATH."""

    callback_parameters: dict[str, str] | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        server = cast(_CallbackServer, self.server)
        split_path = urllib.parse.urlsplit(self.path)
        if split_path.path != CALLBACK_PATH or server.callback_parameters is not None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        query = urllib.parse.parse_qs(split_path.query, keep_blank_values=True)
        server.callback_parameters = {key: values[0] for key, values in query.items()}
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(CALLBACK_PAGE)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(CALLBACK_PAGE)

    def log_message(self, format: str, *args: object) -> None:
        # Silencia o log padrão: a URL de retorno contém o código de autorização.
        return


class LoopbackReceiver:
    """Recebe o retorno do login em 127.0.0.1, em porta efêmera escolhida pelo sistema.

    Escuta somente na interface de loopback (RFC 8252, seção 8.3) e encerra ao sair do
    bloco `with`.
    """

    def __init__(self) -> None:
        self._server = _CallbackServer((LOOPBACK_HOST, 0), _CallbackHandler)

    @property
    def redirect_uri(self) -> str:
        return f"http://{LOOPBACK_HOST}:{self._server.server_port}{CALLBACK_PATH}"

    def wait_for_callback(self, timeout_seconds: float) -> dict[str, str]:
        """Bloqueia até receber o retorno ou esgotar o tempo."""
        deadline = time.monotonic() + timeout_seconds
        while self._server.callback_parameters is None:
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                raise OidcError("tempo esgotado aguardando o retorno do login no navegador")
            self._server.timeout = remaining_seconds
            self._server.handle_request()
        return self._server.callback_parameters

    def close(self) -> None:
        self._server.server_close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def extract_authorization_code(
    callback_parameters: Mapping[str, str], *, expected_state: str
) -> str:
    """Valida o retorno (state e erro) e devolve o código de autorização."""
    received_state = callback_parameters.get("state", "")
    if not secrets.compare_digest(received_state.encode(), expected_state.encode()):
        raise OidcError("o state do retorno não confere com o da requisição; login descartado")
    provider_error = callback_parameters.get("error")
    if provider_error is not None:
        description = callback_parameters.get("error_description")
        suffix = f": {description}" if description else ""
        raise OidcError(f"o provedor recusou o login ({provider_error}{suffix})")
    authorization_code = callback_parameters.get("code")
    if not authorization_code:
        raise OidcError("o retorno do login não contém o código de autorização")
    return authorization_code


def exchange_authorization_code(
    metadata: ProviderMetadata,
    *,
    client_id: str,
    authorization_code: str,
    redirect_uri: str,
    code_verifier: str,
) -> TokenResponse:
    """Troca o código de autorização pelos tokens (cliente público, sem segredo)."""
    operation = "troca do código por tokens"
    form = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
        }
    ).encode()
    request = urllib.request.Request(  # noqa: S310 (esquema validado por ensure_secure_url)
        metadata.token_endpoint,
        data=form,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    payload = _request_json(request, operation=operation)

    token_type = _require_string(payload, "token_type", operation=operation)
    if token_type.lower() != "bearer":
        raise OidcError(f"{operation}: token_type não suportado: {token_type}")
    expires_in = payload.get("expires_in")
    if not isinstance(expires_in, int) or isinstance(expires_in, bool) or expires_in <= 0:
        raise OidcError(f"{operation}: campo obrigatório ausente ou inválido: expires_in")
    return TokenResponse(
        access_token=_require_string(payload, "access_token", operation=operation),
        token_type=token_type,
        expires_in_seconds=expires_in,
        refresh_token=_optional_string(payload, "refresh_token", operation=operation),
        id_token=_optional_string(payload, "id_token", operation=operation),
        scope=_optional_string(payload, "scope", operation=operation),
    )


def fetch_userinfo(metadata: ProviderMetadata, access_token: str) -> dict[str, object]:
    """Consulta o userinfo endpoint com o access token."""
    request = urllib.request.Request(  # noqa: S310 (esquema validado por ensure_secure_url)
        metadata.userinfo_endpoint,
        headers={"Accept": "application/json", "Authorization": f"Bearer {access_token}"},
    )
    return _request_json(request, operation="consulta do userinfo")


def run_authorization_code_flow(
    metadata: ProviderMetadata,
    *,
    client_id: str,
    scopes: Sequence[str],
    present_authorization_url: Callable[[str], None],
    timeout_seconds: float,
) -> TokenResponse:
    """Executa o fluxo completo: PKCE, navegador, retorno em loopback e troca do código.

    `present_authorization_url` recebe a URL de autorização e é responsável por exibi-la
    ao usuário e abrir o navegador.
    """
    pkce_pair = create_pkce_pair()
    state = secrets.token_urlsafe(32)
    with LoopbackReceiver() as receiver:
        redirect_uri = receiver.redirect_uri
        present_authorization_url(
            build_authorization_url(
                metadata,
                client_id=client_id,
                redirect_uri=redirect_uri,
                scopes=scopes,
                state=state,
                code_challenge=pkce_pair.code_challenge,
            )
        )
        callback_parameters = receiver.wait_for_callback(timeout_seconds)
    authorization_code = extract_authorization_code(callback_parameters, expected_state=state)
    return exchange_authorization_code(
        metadata,
        client_id=client_id,
        authorization_code=authorization_code,
        redirect_uri=redirect_uri,
        code_verifier=pkce_pair.code_verifier,
    )
