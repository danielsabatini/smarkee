# core-user-publisher

Publisher de `core.user` (`srv-core-user-publisher`), componente autocontido e sexto papel do loop (`.decisions/0019-publisher-como-sexto-papel.md`).

Publica no transporte, em ordem e de forma sequencial, o que o Manager registrou no **outbox** do tipo (`core.user_outbox`). **Não executa regra de negócio**: o Subject e o payload já estão na linha do outbox.

- **Entrega:** *pelo menos uma vez*. Só marca `published_at` depois da confirmação do transporte, que deduplica por `Nats-Msg-Id` (o `messageId`). Antes de publicar, preenche o `publishedAt` do payload.
- **Ordem:** publicação sequencial; um erro interrompe o lote. Uma única instância ativa por outbox, por trava consultiva **de sessão** do PostgreSQL (conexão dedicada e direta, sem *pooling* de transação). Antes de cada lote confirma que ainda detém a trava; se a perder, reconecta e disputa de novo.
- **Falha transitória** (NATS indisponível, tempo esgotado): repete com *backoff* de 1 s até 30 s, mantendo a ordem.
- **Falha permanente** (mensagem grande demais ou inválida): não descarta nem pula a mensagem, porque isso quebraria a ordem por recurso. Registra `ERROR` com `sequence` e `message_id` e sai de `ready`; a saída é uma atuação humana (decisão 0018).
- **Privilégio:** papel de banco `core_user_publisher` (só `SELECT` no outbox e `UPDATE (published_at)`) e identidade NATS `srv-core-user-publisher` (publica no emissor `manager`, em nome do Manager).

## Estrutura (decisão 0017)

```text
src/core_user_publisher/
  domain/      tipos puros: PublishError (com `permanent`) e PublicationResult
  outbox/      leitura em lote, trava consultiva, marcação e laço de publicação
  transport/   conexão e publicação no NATS JetStream
  http/        servidor de saúde (/health/live, /health/ready, /health/startup; decisão 0018)
  main.py
```

`tests/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador.

## Configuração

Variáveis `CORE_USER_PUBLISHER_<SEÇÃO>_<CAMPO>`, sem arquivo de configuração. Obrigatórias, sem default: `CORE_USER_PUBLISHER_DATABASE_PASSWORD`, `CORE_USER_PUBLISHER_NATS_PASSWORD`. Os demais valores e defaults estão em `src/core_user_publisher/settings.py`.

## Desenvolvimento

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest        # os testes de integração exigem a stack de dev e são pulados sem ela
```
