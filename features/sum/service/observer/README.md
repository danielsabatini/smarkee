# sum-service-observer

Observer de `sum.service` (`sum-service-observer`), componente autocontido (decisões 0015 e 0033).

**Estado:** a leitura e a observação estão prontas e testadas:

- `provider/zitadel.py`: leitura somente de leitura do Zitadel (sem nenhuma escrita), com a conta
  `sum-service-observer`. Lê se o usuário existe e as autorizações nos projetos de roles configurados, na
  organização `register`.
- `domain/observation.py`: traduz a leitura para `present` (com as roles do serviço), `absent` (só quando o
  Zitadel confirma que o usuário não existe) ou `unknown` (qualquer falha de leitura, nunca `absent`).
- `message.py`: monta o envelope `observed` validado pelo contrato, com o subject
  `observer.observed.sum.service.<resourceId>.changed`.

**Não está pronto:** o motor que decide quando observar (ao receber um `desired`, depois de cada resultado e
periodicamente, com jitter e partição por `resourceId`), a publicação no NATS e o processo.

**Verificado no Zitadel de dev (2026-10-15):** um usuário temporário com `ipm.organization.get` no
`roles-ipm` foi observado como `present` com essa role; um identificador inexistente foi observado como
`absent`. O usuário temporário foi removido.

## Testes

```bash
uv run pytest
uv run ruff check . && uv run pyright
```
