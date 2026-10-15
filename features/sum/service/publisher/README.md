# sum-service-publisher

Publisher de `sum.service` (`sum-service-publisher`), componente autocontido (decisão 0015). Lê o outbox
gravado pelo Manager e publica no NATS (decisão 0033).

## Regras

- Uma instância publica por vez, por trava consultiva de sessão.
- O envelope é validado de forma estrita antes de sair; o Publisher acrescenta `publishedAt` e
  `publishedBy` (`sum-service-publisher`). O `emitter` continua `manager`.
- O `Nats-Msg-Id` é o `messageId`: o transporte deduplica reenvios.
- `published_at` só é marcado depois da confirmação do transporte.
- Mensagem fora do envelope, ou recusa permanente do transporte, para o laço e o processo sai com código 1.
  A mensagem continua pendente: quem opera decide.

## Configuração

`SUM_SERVICE_PUBLISHER_<SEÇÃO>_<CAMPO>`: `DATABASE_PASSWORD` e `NATS_PASSWORD` são obrigatórias. Papel do banco:
`sum_service_publisher_login` (lê o outbox e atualiza só `published_at`).

## Testes

```bash
uv run pytest                  # unitários e de integração (os de integração são pulados sem as variáveis)
uv run ruff check . && uv run pyright
```

Variáveis dos testes de integração: `SUM_SERVICE_PUBLISHER_TEST_URL`, `..._TEST_MANAGER_URL` (grava a linha
do outbox), `..._TEST_MAINTENANCE_URL` (limpeza) e `..._TEST_NATS_URL`, `..._TEST_NATS_USER`,
`..._TEST_NATS_PASSWORD`. O teste de publicação usa um Stream temporário e não toca no `DESIRED`.

## Não verificado

A publicação no subject real `manager.desired.sum.service.<resourceId>.changed` com o Publisher rodando
contra o Stream `DESIRED` do dev: não foi feita para não deixar mensagens de teste no Stream.
