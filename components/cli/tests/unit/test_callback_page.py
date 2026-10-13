"""Página de retorno do login: autocontida, sem dados do provedor e com política restrita."""

import re
import threading
import urllib.request

from sk.callback_page import CONTENT_SECURITY_POLICY, render_callback_page
from sk.oidc import LoopbackReceiver


def text(page: bytes) -> str:
    return page.decode("utf-8")


def test_success_page_confirms_the_login_in_portuguese() -> None:
    page = text(render_callback_page(success=True))
    assert "Login concluído" in page
    assert 'lang="pt-BR"' in page
    assert "Esta janela pode ser fechada" in page


def test_failure_page_says_how_to_retry() -> None:
    page = text(render_callback_page(success=False))
    assert "Login não concluído" in page
    assert "sk auth login" in page


def test_pages_load_nothing_external() -> None:
    for success in (True, False):
        page = text(render_callback_page(success=success))
        assert not re.search(r'(src|href)="(https?:)?//', page)
        assert "<script" not in page.lower()


def test_the_logo_is_embedded_not_linked() -> None:
    page = text(render_callback_page(success=True))
    assert 'src="data:image/png;base64,' in page


def test_the_policy_only_allows_inline_style_and_image() -> None:
    assert CONTENT_SECURITY_POLICY == "default-src 'none'; style-src 'unsafe-inline'; img-src data:"


def test_the_failure_page_never_echoes_provider_values() -> None:
    page = text(render_callback_page(success=False))
    assert "access_denied" not in page
    assert "<script" not in page.lower()


def test_the_callback_server_serves_the_page_with_the_policy() -> None:
    """Pelo receptor de retorno real: o navegador recebe a página e a política de conteúdo."""
    with LoopbackReceiver() as receiver:
        # O login espera pelos parâmetros enquanto o navegador faz o GET ao retorno.
        waiter = threading.Thread(target=receiver.wait_for_callback, args=(10,), daemon=True)
        waiter.start()
        with urllib.request.urlopen(f"{receiver.redirect_uri}?code=abc&state=xyz") as response:
            body = response.read().decode("utf-8")
            assert response.headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY
            assert response.headers["Cache-Control"] == "no-store"
        waiter.join(timeout=10)
    assert "Login concluído" in body
    assert "abc" not in body


def test_the_embedded_logo_is_the_full_brand_not_only_the_symbol() -> None:
    """Regressão: a página mostra o logo completo (símbolo e nome), com as dimensões esperadas."""
    import base64
    import struct

    from sk.callback_page import LOGO_PNG_BASE64

    png = base64.b64decode(LOGO_PNG_BASE64)
    width, height = struct.unpack(">II", png[16:24])  # cabeçalho IHDR do PNG
    assert (width, height) == (480, 173)
