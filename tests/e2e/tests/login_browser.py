"""Comando para a variável BROWSER: entrega o endereço de login do `sk` a um navegador falso.

O `sk auth login` abre o navegador com o endereço de autorização. Este script o recebe (primeiro
argumento), faz o login com `E2E_LOGIN_NAME` e `E2E_LOGIN_PASSWORD` e entrega o retorno ao servidor
local do `sk`, como o navegador faria.

Sai sempre com 0: um código diferente faria o Python tentar o navegador real da máquina, que poderia
concluir o login com outra sessão aberta. A falha vai para o arquivo de `E2E_BROWSER_LOG`.
"""

import os
import sys
import traceback
import urllib.parse
from pathlib import Path

from browser import Browser


def main() -> None:
    authorization_url = sys.argv[1]
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(authorization_url).query)
    browser = Browser()
    try:
        browser.sign_in(
            authorization_url,
            os.environ["E2E_LOGIN_NAME"],
            os.environ["E2E_LOGIN_PASSWORD"],
            callback=query["redirect_uri"][0],
        )
    finally:
        browser.close()


try:
    main()
except Exception:
    Path(os.environ.get("E2E_BROWSER_LOG", os.devnull)).write_text(traceback.format_exc())
sys.exit(0)
