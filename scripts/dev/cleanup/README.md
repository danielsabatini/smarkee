# smarkee-dev-cleanup

Limpeza segura dos dados de teste do ambiente de desenvolvimento. É uma **ferramenta de operação**, e não um componente da plataforma nem um teste.

Os testes (e2e, de integração e a jornada) criam usuários, Organizations e ligações de serviço reais. Quando um teste falha no meio, sobra resíduo no Zitadel, no SSOT, no NATS e no Mailpit. Este comando acha **só** o que é de teste e remove.

```bash
cd scripts/dev/cleanup && uv sync
uv run smarkee-dev-cleanup            # mostra o resíduo; sai com 1 se houver, 0 se estiver limpo
uv run smarkee-dev-cleanup --apply    # remove; sai com 1 se, depois de remover, ainda sobrar algo
uv run smarkee-dev-cleanup --orphans [--apply]   # modo explícito, mais amplo (veja abaixo)
```

## O que é "de teste"

Nunca é "tudo": cada alvo é identificado por um padrão (`src/smarkee_dev_cleanup/model.py`).

| Alvo | Padrão |
|---|---|
| Organization (Zitadel e SSOT) | nome começando por `conf-`, `acme-`, `loop-`, `dup-`, `chaos-`, `e2e-`, `probe-`, `ver-` ou `cons-`, ou `org-` ou `renamed-` seguidos de 10 hexadecimais (os nomes dos testes de integração do Manager da Organization: o padrão e o do teste de renomear), e, no Zitadel, ID em formato de UUID (o `resourceId`) |
| Usuário (Zitadel e SSOT) | e-mail de `example.com` começando por `e2e-`, `loop.`, `conf.`, `chaos.`, `cons.` ou `sa.test.` |
| Histórico de recursos de teste já removidos (SSOT) | recursos **sem linha principal** que ainda têm outbox, Operations ou resultados, e cujo rótulo gravado no outbox é de teste (e-mail, nome ou, nas ligações, dono de teste). O que não tem rótulo, ou tem rótulo que não é de teste, é mantido e só aparece no aviso "Histórico mantido" |
| Ligação de serviço (SSOT) | dono de teste, ou dono que nem existe mais no Zitadel (órfã) |
| Mensageria (NATS) | as mensagens dos recursos acima nos Streams `REQUESTED`, `DESIRED`, `OBSERVED`, `RESULT` e `UPDATED` (o `ACTION` é particionado pelo servidor e não dá para filtrar por recurso) |
| Mailpit | mensagens para os rótulos de e-mail de teste acima |

Organizations de nome real, usuários de e-mail real e as organizações do sistema (`smarkee`, `core`, `register`) nunca são tocadas; há teste para isso.

## Como remove

1. **Pelo loop**, como a plataforma faz: pede a remoção (`requested` de `delete`) das Organizations e dos usuários que ainda estão `Ready` e espera o `removed` (até 45 s).
2. **Direto**, só o que o loop não removeu, e o histórico (outbox, Operations e resultados) dos recursos de teste que o loop removeu, na própria execução ou antes (órfãos de uma queda): Zitadel pela API v2, SSOT pelos papéis de login de cada módulo (o Manager apaga a linha e o `maintenance`, o apoio), e depois a mensageria e os e-mails.
3. **Verifica**: procura de novo e falha se sobrar algo.

## Segurança

- Só fala com os endereços fixos de dev (Zitadel `localhost:8080`, banco `localhost:5432`, NATS `localhost:4222` e Mailpit `localhost:8025`); as variáveis `CLEANUP_ZITADEL_URL`, `CLEANUP_DATABASE_HOST`, `CLEANUP_NATS_URL` e `CLEANUP_MAIL_URL` são **recusadas**, para não apontar o comando para outro ambiente.
- A chave do `platform-bootstrap` é lida na memória, do volume `identity-bootstrap` (ou de `CLEANUP_ZITADEL_KEY_FILE`), e nunca é impressa nem gravada. A senha do NATS vem de `infrastructure/dev/messaging/.env` (ou de `CLEANUP_NATS_PASSWORD`).
- Sem `--apply`, nada é alterado.
- `--orphans` é explícito e **mais destrutivo**: além do padrão, remove o histórico (outbox, Operations
  e resultados) de **todo** recurso sem linha principal, tenha ou não rótulo de teste, e as mensagens
  dos Streams (`REQUESTED`, `DESIRED`, `OBSERVED`, `RESULT`, `UPDATED`) de recursos sem linha principal.
  Apaga também experimentos manuais e o histórico que a futura auditoria usaria. Rode antes sem
  `--apply` para ver o que seria removido. Recursos vivos nunca são tocados.

## Desenvolvimento

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest        # a lógica roda contra portas falsas; não toca no ambiente
```
