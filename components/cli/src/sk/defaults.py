"""Endereços padrão da plataforma, usados pelo `sk init` quando o usuário não informa outros.

São os endereços de produção (prd). Não são segredos: o issuer e a URL da API são públicos, e o
client ID é de uma aplicação nativa, que não tem segredo.

`PROVISIONAL_CLIENT_ID` é um marcador: o client ID de produção ainda não existe. O `sk init`
avisa quando o grava, e a troca pelo valor definitivo é pendente (decisão 0023).
"""

PRD_ISSUER = "https://ipm.smarkee.com.br"
PRD_API_URL = "https://api.smarkee.com.br"
PROVISIONAL_CLIENT_ID = "pendente-prd"
