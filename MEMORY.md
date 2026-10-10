# Memória Operacional do Projeto (AI Context)

Em conformidade com o `AGENTS.md` (Seção 35.1), este arquivo atua exclusivamente como a **área de transferência de contexto** entre as sessões dos agentes.

## O que o próximo agente precisa saber agora?

*(Este arquivo deve permanecer compacto. Registre aqui apenas o contexto ativo, tarefas em andamento e dependências imediatas. Remova tarefas finalizadas e lixo geracional. **Não** utilize este arquivo como documentação oficial, governança ou registro de regras permanentes).*

### Estado Atual
- Fase de especificação: `docs/` contém `MESSAGING.md`, `NATS.md`, `SCHEMA.md` e `RESOURCE-CONTROL-LOOP.md`. `MESSAGING.md` foi reescrito.
- `docs/RESOURCE-CONTROL-LOOP.md` foi revisado e `docs/RESOURCE-CONTROL-SECURITY.md` criado. O modelo adotado: o Reconciler consome `desired` e `observed` pela mensageria (sem acesso ao SSOT), com um Stream por `messageType`, `desired`/`observed` em operação `changed` e consumers por classe (trabalho, persistência, estado por instância).
- `components/cli` implementa `sk auth login` (Typer, pydantic-settings; decisões 0007 e 0008). `components/manager` e `features/ipm` continuam esqueletos vazios.
- Organization substitui Tenant (decisão 0006) e é recurso da plataforma no módulo `core` (decisão 0009): `sk organization`, subjects `*.core.organization.*`.
- Em andamento: plano de cadastro e Organization pela API (decisões 0009 a 0014). Concluídas: Fase A (decisões e docs), Fase B (contratos, snake_case, lint `N`, migrações 0002 e 0003) e a parte de Zitadel da Fase C: no dev, org `core` com o projeto `smarkee` (ID `394490764261851138`), roles por ação, app `cli` JWT (client ID `394490764379357186`), cadastro público desligado, service accounts `core-user-executor` e `core-organization-executor` com chaves no volume `identity-bootstrap`; `tenant1` removida. Papéis mínimos, claims do token e erro 409 de ID duplicado verificados. **Pendente da Fase C:** servidor de e-mail em dev (captura) e teste da ativação sem senha; rota do Kong para a API e limite de taxa (dependem do serviço); allowlist de caminhos do Zitadel em stg e prd; mecanismo definitivo da configuração do Zitadel. Próximas: D serviço `features/core` (API primeiro) e E CLI. O Manager não pode usar `RETURNING` no outbox (sem `SELECT`, verificado).
- Pendente do usuário no dev: validar `sk auth init --force ... --client-id 394490764379357186` e `sk auth login` (como `admin@smarkee.ipm-dev.smarkee.com.br`, que recebeu `platform.admin`); decidir se a conta `danielsabatini@gmail.com` também recebe `platform.admin`; depois remover o projeto `smarkee` antigo da org `smarkee`. Os scripts temporários da configuração estão em `.workspace/` (não versionados).

### Tarefas Pendentes
- Executar o primeiro `sk auth login` real contra a aplicação `cli` nova (só o discovery foi verificado).
- Pendência da decisão 0006: regras de nome de namespace do OpenBao.
- Direção definida em 2026-10-10 (decisões 0013 e 0014): API → CLI → console web; Zitadel só com o necessário ao OIDC exposto e registro desligado; `sk register --name --surname --email` (sem senha, ativação por e-mail do Zitadel) cria o User do módulo `core` pelo loop; Organization só por usuário autenticado, com e-mail verificado e cota por dono; org `core` no Zitadel para usuários cadastrados e service accounts dos Executors.
- Suporte a `ZITADEL_FIRSTINSTANCE_ORG_MACHINE_*` confirmado no `steps.yaml` da v4.19.4; a criação real só será verificada ao recriar a instância. Em dev, as contas foram criadas pela API.
- Validar em ambiente real (não há broker para testar): configuração dos Streams e das ACLs de JetStream descritas em `docs/NATS.md`, e a população do `AUDIT` a partir de Streams `WorkQueue` (`REQUESTED`, `ACTION`).
- Validar em ambiente real: `pinned_client` (versão mínima do servidor e comportamento com `max_ack_pending=1`), `inactive_threshold`, Direct Get em `DESIRED` e os Subjects exatos de ACL (criação de consumer com filtro, `MSG.NEXT`, ACK, Direct Get).
- Definir o job de limpeza de tombstones e a identidade administrativa (infraestrutura).
- Agents e skills revisados: skills `nats` e `postgresql` são guias de procedimento (leitura por padrão; mutação declarativa e aprovada). Pendente de validação: nomes das flags da CLI `nats` e do mecanismo de migração (infraestrutura ainda não definida); skills externas de NATS citadas não foram verificadas.
- SSOT (`docs/SSOT.md`, `docs/POSTGRESQL.md`): validar em ambiente real relay com transporte, failover, PITR, proteção em repouso, *pooling* de conexões (trava consultiva exige sessão) e custo de DDL. Chave de idempotência: definida como cabeçalho HTTP `Idempotency-Key` (LOOP §6.1.1); não é transportada no `requested`, que leva o `operationId` derivado (decisão 0002).
- Quando houver implementação: escolher o formato de schema e registrar a decisão em `.decisions/`; formalizar em `schemas/` o envelope comum, os limites padrão e a família de contratos descrita em `docs/SCHEMA.md`.
- Registrar as primeiras ADRs em `.decisions/` (ex.: NATS JetStream, modelo desired/observed).
- Auditar a consistência entre os quatro documentos de `docs/` e entre eles e `.opencode/`.
