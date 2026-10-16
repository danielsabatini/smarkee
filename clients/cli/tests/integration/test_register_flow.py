"""`sk register` contra um servidor HTTP real (loopback), sem nenhum token enviado.

Simula a API do cadastro: responde `202` ao pedido bem formado e registra o que chegou. Não
substitui o teste contra a plataforma de dev (`features/core/user/tests/e2e`).
"""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest
from typer.testing import CliRunner

from sk.main import app

runner = CliRunner()


class Recording(BaseHTTPRequestHandler):
    received: ClassVar[list[dict[str, Any]]] = []
    status: ClassVar[int] = 202

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        Recording.received.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": json.loads(body or b"{}"),
            }
        )
        payload = json.dumps(
            {"resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e", "operationId": "op-1"}
        ).encode()
        self.send_response(Recording.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return None


@pytest.fixture
def api_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for variable in ("SK_CORE_API_URL", "SK_CORE_ALLOW_INSECURE_HTTP"):
        monkeypatch.delenv(variable, raising=False)
    Recording.received = []
    Recording.status = 202
    server = ThreadingHTTPServer(("127.0.0.1", 0), Recording)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_the_request_reaches_the_api_without_any_token(api_server: str, tmp_path: Path) -> None:
    # Há credenciais salvas: o cadastro, mesmo assim, não as envia.
    (tmp_path / "sk").mkdir()
    (tmp_path / "sk" / "credentials.json").write_text(
        json.dumps({"accessToken": "token-que-nao-pode-sair"}), encoding="utf-8"
    )
    result = runner.invoke(
        app,
        [
            "register",
            "--name",
            "Ana",
            "--surname",
            "Souza",
            "--email",
            "ana@example.com",
            "--api-url",
            api_server,
            "--allow-insecure-http",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert "op-1" in result.stdout
    assert "Registration requested" in result.stdout
    request = Recording.received[0]
    assert request["path"] == "/v1/core/users"
    assert request["authorization"] is None
    assert request["body"] == {
        "givenName": "Ana",
        "familyName": "Souza",
        "email": "ana@example.com",
    }
    assert "token-que-nao-pode-sair" not in json.dumps(Recording.received)


def test_plain_http_without_permission_sends_nothing(api_server: str) -> None:
    result = runner.invoke(
        app,
        [
            "register",
            "--name",
            "Ana",
            "--surname",
            "Souza",
            "--email",
            "ana@example.com",
            "--api-url",
            api_server,
        ],
    )
    assert result.exit_code == 2
    assert "without TLS" in result.stderr
    assert Recording.received == []
