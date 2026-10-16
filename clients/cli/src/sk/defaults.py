"""Valores padrão da plataforma: os de produção (prd), usados quando nada os substitui.

São a configuração de quem usa a CLI em produção: ela funciona sem arquivo, sem `sk init` e sem
variável. O arquivo de configuração, as variáveis `SK_*` e as opções só **sobrescrevem** (é o que o
desenvolvimento e o stg fazem). Nada aqui é segredo: o issuer, a URL da API e os IDs de projeto são
públicos, e o client ID é de uma aplicação nativa, que não tem segredo (decisão 0036).

`PROVISIONAL` (18 zeros, o tamanho de um ID do Zitadel) marca o que ainda não existe em produção:
o client ID e os IDs dos projetos de roles só nascem quando o Zitadel de produção for provisionado.
O login recusa um valor provisório e diz qual é, em vez de seguir com um valor que não funciona.
"""

PROVISIONAL = "0" * 18  # zeros no tamanho de um ID do Zitadel (18 dígitos)

PRD_ISSUER = "https://ipm.smarkee.com.br"
PRD_API_URL = "https://api.smarkee.com.br"
PRD_CLIENT_ID = PROVISIONAL
PRD_CORE_PROJECT_ID = PROVISIONAL
PRD_SUM_PROJECT_ID = PROVISIONAL
PRD_IPM_PROJECT_ID = PROVISIONAL
