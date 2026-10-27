# smarkee-dev-republish

Ferramenta operacional de desenvolvimento para recuperação e republicação do estado `desired` vigente a partir do SSOT PostgreSQL (`dbname=ssot`).

## Motivação e Objetivos

Conforme o plano de evolução do Resource Control Loop e os pilares de Simplicidade e Resiliência (`AGENTS.md` §2.1):
1. Caso o stream NATS JetStream `DESIRED` seja recriado, sofra expiração de retenção ou perda de estado no ambiente de dev, o SSOT é a Fonte Única da Verdade (`SSOT.md`).
2. A ferramenta lê o estado `desired` vigente em cada tabela `<module>.<resource_type>` e gera mensagens canônicas com `Nats-Msg-Id` determinístico baseado em `(module, resource_type, resource_id, desired_generation)`.
3. Oferece dois modos de destino (`--target`):
   - `outbox` (padrão): enfileira nas tabelas `<tipo>_outbox` do SSOT para publicação controlada pelo papel Publisher de cada feature via `ON CONFLICT (message_id) DO NOTHING`.
   - `nats`: publica diretamente no NATS JetStream com cabeçalho `Nats-Msg-Id`, acionando a deduplicação nativa do JetStream.

## Uso

```bash
cd scripts/dev/republish && uv sync

# Visualizar o plano (dry-run, seguro, não altera nada)
uv run smarkee-dev-republish

# Republicar enfileirando nas tabelas outbox do SSOT
uv run smarkee-dev-republish --apply

# Republicar diretamente no NATS JetStream
uv run smarkee-dev-republish --target nats --apply

# Filtrar por módulo ou tipo
uv run smarkee-dev-republish --module ipm --type user --apply
```
