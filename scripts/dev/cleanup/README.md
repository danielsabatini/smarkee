# smarkee-dev-cleanup

Limpeza segura dos dados de teste do ambiente de desenvolvimento. É uma **ferramenta de operação**, e não um componente da plataforma nem um teste.

Os testes (e2e, de integração e a jornada) criam usuários, Organizations e ligações de serviço reais. Quando um teste falha no meio, sobra resíduo no Zitadel, no SSOT, no NATS e no Mailpit. Este comando acha **só** o que é de teste e remove.

```bash
cd scripts/dev/cleanup && uv sync
uv run smarkee-dev-cleanup            # mostra o resíduo; sai com 1 se houver, 0 se estiver limpo
uv run smarkee-dev-cleanup --apply    # remove; sai com 1 se, depois de remover, ainda sobrar algo
```

## O que é "de teste"

Nunca é "tudo": cada alvo é identificado por um padrão (`src/smarkee_dev_cleanup/model.py`).

| Alvo | Padrão |
|---|---|
| Organization (Zitadel e SSOT) | nome começando por `conf-`, `acme-`, `loop-`, `dup-`, `chaos-`, `e2e-`, `probe-`, `ver-` ou `cons-` e, no Zitadel, ID em formato de UUID (o `resourceId`) |
| Usuário (Zitadel e SSOT) | e-mail de `example.com` começando por `e2e-`, `loop.`, `conf.`, `chaos.`, `cons.` ou `sa.test.` |
| Ligação de serviço (SSOT) | dono de teste, ou dono que nem existe mais no Zitadel (órfã) |
| Mensageria (NATS) | as mensagens dos recursos acima nos Streams `REQUESTED`, `DESIRED`, `OBSERVED`, `RESULT` e `UPDATED` (o `ACTION` é particionado pelo servidor e não dá para filtrar por recurso) |
| Mailpit | mensagens para os rótulos de e-mail de teste acima |

Organizations de nome real, usuários de e-mail real e as organizações do sistema (`smarkee`, `core`, `register`) nunca são tocadas; há teste para isso.

## Como remove

1. **Pelo loop**, como a plataforma faz: pede a remoção (`requested` de `delete`) das Organizations e dos usuários que ainda estão `Ready` e espera o `removed` (até 45 s).
2. **Direto**, só o que o loop não removeu (órfãos de uma queda): Zitadel pela API v2, SSOT pelos papéis de login de cada módulo (o Manager apaga a linha e o `maintenance`, o apoio), e depois a mensageria e os e-mails.
3. **Verifica**: procura de novo e falha se sobrar algo.

## Segurança

- Só fala com os endereços fixos de dev (Zitadel `localhost:8080`, banco `localhost:5432`, NATS `localhost:4222` e Mailpit `localhost:8025`); as variáveis `CLEANUP_ZITADEL_URL`, `CLEANUP_DATABASE_HOST`, `CLEANUP_NATS_URL` e `CLEANUP_MAIL_URL` são **recusadas**, para não apontar o comando para outro ambiente.
- A chave do `platform-bootstrap` é lida na memória, do volume `identity-bootstrap` (ou de `CLEANUP_ZITADEL_KEY_FILE`), e nunca é impressa nem gravada. A senha do NATS vem de `infrastructure/dev/broker/.env` (ou de `CLEANUP_NATS_PASSWORD`).
- Sem `--apply`, nada é alterado.

## Desenvolvimento

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest        # a lógica roda contra portas falsas; não toca no ambiente
```
