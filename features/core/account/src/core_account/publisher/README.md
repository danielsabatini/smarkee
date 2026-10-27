# core-account-publisher

Publisher de `core.account` (`core-account-publisher`), um dos três papéis da imagem única `core-account` (decisões 0063, 0065 e 0098), ao lado da API e do Controller.

Publica no transporte, em ordem e de forma sequencial, o que a API (`desired`) e o Controller (`updated`) registraram no **outbox** do tipo (`core.account_outbox`). **Não executa regra de negócio**: o Subject e o payload já estão na linha do outbox.

- **Entrega:** *pelo menos uma vez*. Só marca `published_at` depois da confirmação do transporte, que deduplica por `Nats-Msg-Id` (o `messageId`). Antes de publicar, preenche o `publishedAt` e o `publishedBy` (`core-account-publisher`) do payload.
- **Ordem:** publicação sequencial; um erro interrompe o lote. Uma única instância ativa por outbox, por trava consultiva **de sessão** do PostgreSQL (conexão dedicada e direta, sem *pooling* de transação). Antes de cada lote confirma que ainda detém a trava; se a perder, reconecta e disputa de novo.
- **Falha transitória** (NATS indisponível, tempo esgotado): repete com *backoff* de 1 s até 30 s, mantendo a ordem.
- **Falha permanente** (mensagem grande demais ou fora do envelope): não descarta nem pula a mensagem, porque isso quebraria a ordem por recurso. Registra `ERROR` com `sequence` e `message_id` e sai de `ready`; a saída é uma atuação humana (decisão 0018).
- **Privilégio:** papel de banco `core_account_publisher` (só `SELECT` no outbox e `UPDATE (published_at)`) e identidade NATS `core-account-publisher` (o Subject já vem na linha do outbox).

## Estrutura (decisão 0017)

```text
src/core_account/publisher/
  domain/      tipos puros: PublicationResult e PublicationRejectedError (mensagem fora do envelope)
  outbox/      leitura em lote, validação do envelope, trava consultiva, marcação e laço de publicação
  main.py
```

`tests/common/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador.

## Configuração

Variáveis `CORE_ACCOUNT_PUBLISHER_<SEÇÃO>_<CAMPO>`, sem arquivo de configuração. Obrigatórias, sem default: `CORE_ACCOUNT_PUBLISHER_DATABASE_PASSWORD`, `CORE_ACCOUNT_PUBLISHER_MESSAGING_PASSWORD`. Os demais valores e defaults estão em `src/core_account/publisher/settings.py`.

## Desenvolvimento

```bash
# Na raiz da feature (features/core/account), que é o projeto único:
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest tests/publisher  # os testes de integração exigem a stack de dev e são pulados sem ela
```
