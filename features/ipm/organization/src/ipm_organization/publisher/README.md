# ipm-organization-publisher

Publisher de `ipm.organization` (`ipm-organization-publisher`), um dos seis papéis da imagem única `ipm-organization` (decisão 0063) e sexto papel do loop (`.decisions/0019-publisher-como-sexto-papel.md`).

Publica no transporte, em ordem e de forma sequencial, o que o Manager registrou no **outbox** do tipo (`ipm.organization_outbox`). **Não executa regra de negócio**: o Subject e o payload já estão na linha do outbox.

- **Entrega:** *pelo menos uma vez*. Só marca `published_at` depois da confirmação do transporte, que deduplica por `Nats-Msg-Id` (o `messageId`). Antes de publicar, preenche o `publishedAt` e o `publishedBy` (`ipm-organization-publisher`) do payload.
- **Ordem:** publicação sequencial; um erro interrompe o lote. Uma única instância ativa por outbox, por trava consultiva **de sessão** do PostgreSQL (conexão dedicada e direta, sem *pooling* de transação). Antes de cada lote confirma que ainda detém a trava; se a perder, reconecta e disputa de novo.
- **Falha transitória** (NATS indisponível, tempo esgotado): repete com *backoff* de 1 s até 30 s, mantendo a ordem.
- **Falha permanente** (mensagem grande demais ou inválida): não descarta nem pula a mensagem, porque isso quebraria a ordem por recurso. Registra `ERROR` com `sequence` e `message_id` e sai de `ready`; a saída é uma atuação humana (decisão 0018).
- **Privilégio:** papel de banco `ipm_organization_publisher` (só `SELECT` no outbox e `UPDATE (published_at)`) e identidade NATS `ipm-organization-publisher` (entrega no Subject do emissor `manager`, o autor da decisão).

## Estrutura (decisão 0017)

```text
src/ipm_organization/publisher/
  domain/      tipos puros: PublishError (com `permanent`) e PublicationResult
  outbox/      leitura em lote, trava consultiva, marcação e laço de publicação
  transport/   conexão e publicação no NATS JetStream
  http/        servidor de saúde (/health/live, /health/ready, /health/startup; decisão 0018)
  main.py
```

`tests/common/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador.

## Configuração

Variáveis `IPM_ORGANIZATION_PUBLISHER_<SEÇÃO>_<CAMPO>`, sem arquivo de configuração. Obrigatórias, sem default: `IPM_ORGANIZATION_PUBLISHER_DATABASE_PASSWORD`, `IPM_ORGANIZATION_PUBLISHER_NATS_PASSWORD`. Os demais valores e defaults estão em `src/ipm_organization/publisher/settings.py`.

## Desenvolvimento

```bash
# Na raiz da feature (features/ipm/organization), que é o projeto único:
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest tests/publisher  # os testes de integração exigem a stack de dev e são pulados sem ela
```
