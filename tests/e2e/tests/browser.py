"""Navegador mínimo para a interface de login do provedor de identidade (páginas HTML sem script).

Faz o que a pessoa faz no navegador: abre o link do e-mail, preenche e envia os formulários. Não usa
nenhuma credencial privilegiada: só o que a pessoa teria (o link do e-mail, o e-mail e a senha).
"""

import urllib.parse
from html.parser import HTMLParser

import httpx

MAXIMUM_REDIRECTS = 15
MFA_PROMPT_ACTION = "/ui/login/mfa/prompt"
AUTHORIZE_CALLBACK_PATH = "/oauth/v2/authorize/callback"


class FormNotFoundError(Exception):
    """A página não tem o formulário esperado."""


class _FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.actions: list[str] = []
        self.forms: list[dict[str, str]] = []
        self._fields: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if tag == "form":
            self._fields = {}
            self.actions.append(values.get("action", ""))
            self.forms.append(self._fields)
        elif tag == "input" and self._fields is not None and values.get("name"):
            kind = values.get("type")
            chosen = "checked" in values or kind not in ("radio", "checkbox")
            if kind != "submit" and chosen:
                self._fields[values["name"]] = values.get("value", "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._fields = None


def first_form(html: str) -> tuple[str, dict[str, str]]:
    """Endereço de envio e campos (com os valores já preenchidos) do primeiro formulário."""
    parser = _FormParser()
    parser.feed(html)
    if not parser.forms:
        raise FormNotFoundError("a página não tem formulário")
    return parser.actions[0], dict(parser.forms[0])


def first_action(response: httpx.Response) -> str | None:
    """Endereço de envio do primeiro formulário da página, ou `None` se ela não tem formulário."""
    try:
        return first_form(response.text)[0]
    except FormNotFoundError:
        return None


class Browser:
    """Mantém os cookies e segue os redirecionamentos de uma sessão de navegação."""

    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.Client(follow_redirects=False, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def submit_form(self, page_url: str, values: dict[str, str]) -> httpx.Response:
        """Abre a página, preenche o primeiro formulário com `values` e o envia."""
        page = self._client.get(page_url)
        action, fields = first_form(page.text)
        fields.update(values)
        return self._client.post(urllib.parse.urljoin(page_url, action), data=fields)

    def settle(self, response: httpx.Response, callback: str | None = None) -> httpx.Response:
        """Segue os redirecionamentos até uma página. Para antes de `callback`, sem acessá-lo."""
        for _ in range(MAXIMUM_REDIRECTS):
            location = response.headers.get("location")
            if location is None:
                return response
            target = urllib.parse.urljoin(str(response.url), location)
            if callback is not None and target.startswith(callback):
                return response
            response = self._client.get(target)
        raise RuntimeError("redirecionamentos demais")

    def submit_page_form(self, page: httpx.Response, values: dict[str, str]) -> httpx.Response:
        """Preenche o primeiro formulário de uma página já aberta, envia e segue o resultado."""
        action, fields = first_form(page.text)
        fields.update(values)
        sent = self._client.post(urllib.parse.urljoin(str(page.url), action), data=fields)
        return sent

    def sign_in(
        self, authorization_url: str, login_name: str, password: str, callback: str
    ) -> None:
        """Faz o login interativo: usuário e senha, e entrega o retorno ao endereço do `sk`."""
        page = self.settle(self._client.get(authorization_url), callback)
        page = self.settle(self.submit_page_form(page, {"loginName": login_name}), callback)
        final = self.settle(self.submit_page_form(page, {"password": password}), callback)
        if first_action(final) == MFA_PROMPT_ACTION:  # oferta de segundo fator: a pessoa a dispensa
            final = self.settle(self.submit_page_form(final, {"skip": "true"}), callback)
        action = first_action(final)
        if action is not None and AUTHORIZE_CALLBACK_PATH in action:  # o que o script da página faz
            final = self.settle(
                self._client.get(urllib.parse.urljoin(str(final.url), action)), callback
            )
        location = urllib.parse.urljoin(str(final.url), final.headers.get("location", ""))
        if not location.startswith(callback):
            raise RuntimeError("o login não terminou no retorno do sk")
        self._client.get(location)
