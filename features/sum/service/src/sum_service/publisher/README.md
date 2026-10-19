# sum-service-publisher

Publisher de `sum.service` (`sum-service-publisher`), um dos seis papéis da imagem única `sum-service` (decisões 0015 e 0063), com processo e contêiner próprios. Veja o [README da feature](../../../README.md). Lê o outbox
gravado pelo Manager e publica no NATS (decisão 0033).

## Regras

- Uma instância publica por vez, por trava consultiva de sessão, mantida enquanto publica e reconquistada se a conexão cair.
- Estrutura: `domain/` (tipos puros), `outbox/` (conexão dedicada e publicação do lote) e `transport/` (JetStream).
- O envelope é validado de forma estrita antes de sair; o Publisher acrescenta `publishedAt` e
  `publishedBy` (`sum-service-publisher`). O `emitter` continua `manager`.
- O `Nats-Msg-Id` é o `messageId`: o transporte deduplica reenvios.
- `published_at` só é marcado depois da confirmação do transporte, mensagem a mensagem.
- Mensagem fora do envelope, ou recusa permanente do transporte, para o lote e registra `ERROR` com `sequence` e
  `message_id`. A mensagem continua pendente (a ordem é preservada) e o Publisher sai de `ready` (verificação
  `publication`), sem derrubar o processo: quem opera decide (decisão 0018). Erro transitório tem recuo exponencial.

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

## Verificação

A publicação no subject real `manager.desired.sum.service.<resourceId>.changed`, com o Publisher no Compose, é
exercida pela suíte e2e (`../../../tests/e2e`), inclusive com o Publisher parado durante um pedido.
