# Zitadel de dev: conformidade da estrutura

Esta suíte é um **teste**, não um componente. Somente leitura: confere se o Zitadel de dev tem a estrutura que as
decisões 0010, 0014, 0026, 0027 e 0028 mandam, e não altera nada. Usa só a API v2 do Zitadel (decisão 0029).

| O que confere | Decisão |
|---|---|
| Organizações `smarkee`, `core` e `register`; cadastro público desligado | 0013, 0026 |
| Projetos de roles na `core` (roles no token e verificação de role), roles no padrão `<módulo>.<tipo>.<ação>` com `group` | 0010, 0028 |
| Aplicação `cli` (nativa, PKCE sem segredo, access token JWT, redirect e concessões) | 0007, 0010 |
| Um projeto de roles por módulo; um Project Grant por projeto só com as roles de ação (sem `*.admin`) | 0027, 0032 |
| Contas de serviço na `core`; Executor (`ORG_USER_CREATOR`) e Observer com papel só na `register`; Executor do User `PROJECT_GRANT_OWNER` só nos Grants de `core` e `sum` | 0027, 0032 |
| Membros da instância (`platform-bootstrap`, `core-organization-executor`) | 0011 |
| Na `core`, só operadores (cada autorização com uma `*.admin` e roles de ação); o operador padrão com todas as roles; a `register` sem projeto próprio | 0027, 0031 |

A estrutura é criada à mão (`infrastructure/dev/README.md`, "Configuração do Zitadel para a plataforma"). Esta suíte diz se ela
está como o desenho manda, e é o roteiro de conferência depois de recriar a instância (`docker compose down -v`).

Requer a chave da conta `platform-bootstrap`. Grave-a fora do repositório (em `.workspace/`, ignorado) e apague depois:

```bash
mkdir -p ../../../../.workspace/zitadel
docker run --rm -v identity-bootstrap:/b:ro alpine cat /b/service-account-platform-bootstrap.json \
  > ../../../../.workspace/zitadel/platform-bootstrap.json
export CONFORMANCE_ZITADEL_KEY_FILE=$PWD/../../../../.workspace/zitadel/platform-bootstrap.json
uv sync
uv run pytest
rm ../../../../.workspace/zitadel/platform-bootstrap.json
```

| Variável | Padrão | Uso |
|---|---|---|
| `CONFORMANCE_ZITADEL_KEY_FILE` | (sem padrão; sem ela, os testes são pulados) | Chave JSON do `platform-bootstrap` |
| `CONFORMANCE_ZITADEL_URL` | `http://localhost:8080` | Gateway do Zitadel |
| `CONFORMANCE_ZITADEL_HOST` | `ipm-dev.smarkee.com.br:8080` | Cabeçalho `Host` |
| `CONFORMANCE_ZITADEL_ISSUER` | `http://ipm-dev.smarkee.com.br:8080` | Audience da assertion |
