# Memória Operacional do Projeto (AI Context)

Em conformidade com o `AGENTS.md` (Seção 35.1), este arquivo atua exclusivamente como a **área de transferência de contexto** entre as sessões dos agentes.

## O que o próximo agente precisa saber agora?

*(Este arquivo deve permanecer compacto. Registre aqui apenas o contexto ativo, tarefas em andamento e dependências imediatas. Remova tarefas finalizadas e lixo geracional. **Não** utilize este arquivo como documentação oficial, governança ou registro de regras permanentes).*

### Estado Atual
- Fase de especificação: `docs/` contém `MESSAGING.md`, `NATS.md`, `SCHEMA.md` e `RESOURCE-CONTROL-LOOP.md`. `MESSAGING.md` foi reescrito.
- `docs/RESOURCE-CONTROL-LOOP.md` foi revisado e `docs/RESOURCE-CONTROL-SECURITY.md` criado. O modelo adotado: o Reconciler consome `desired` e `observed` pela mensageria (sem acesso ao SSOT), com um Stream por `messageType`, `desired`/`observed` em operação `changed` e consumers por classe (trabalho, persistência, estado por instância).
- `components/cli` implementa `sk auth login` (Typer, pydantic-settings; decisões 0007 e 0008). `components/manager` e `features/ipm` continuam esqueletos vazios.
- Organization substitui Tenant (decisão 0006) e é recurso da plataforma no módulo `core` (decisão 0009): `sk organization`, subjects `*.core.organization.*`.
- Em andamento: plano `sk organization` pelo loop completo (decisões 0010 a 0012). Fases 0 (decisões e docs) e 1 (contratos em `schemas/`, modelos gerados em `features/core`) concluídas; próximas: 2 infraestrutura de dev (usuário de máquina do Executor no Zitadel, migração `core`, serviço e rota), 3 serviço `features/core` colapsado, 4 CLI.

### Tarefas Pendentes
- Zitadel dev: criar o projeto `smarkee` e a aplicação nativa `sk` pelo console (`infrastructure/dev/README.md`, *Login do CLI*) e executar o primeiro `sk auth login` real (só o discovery foi verificado).
- Definir as roles do projeto `smarkee` (internas × delegáveis às organizations por Project Grant).
- Pendências da decisão 0006: entrada no SSOT das orgs criadas pelo autocadastro do Zitadel; erro do Zitadel para `organization_id` repetido; regras de nome de namespace do OpenBao.
- Próximo recurso planejado pelo usuário: `ipm user`, seguindo `docs/RESOURCE-CONTROL-LOOP.md`.
- Confirmar se o Zitadel v4.19.4 cria usuário de máquina com chave JWT por `ZITADEL_FIRSTINSTANCE_ORG_MACHINE_*` (decisão 0011).
- Validar em ambiente real (não há broker para testar): configuração dos Streams e das ACLs de JetStream descritas em `docs/NATS.md`, e a população do `AUDIT` a partir de Streams `WorkQueue` (`REQUESTED`, `ACTION`).
- Validar em ambiente real: `pinned_client` (versão mínima do servidor e comportamento com `max_ack_pending=1`), `inactive_threshold`, Direct Get em `DESIRED` e os Subjects exatos de ACL (criação de consumer com filtro, `MSG.NEXT`, ACK, Direct Get).
- Definir o job de limpeza de tombstones e a identidade administrativa (infraestrutura).
- Agents e skills revisados: skills `nats` e `postgresql` são guias de procedimento (leitura por padrão; mutação declarativa e aprovada). Pendente de validação: nomes das flags da CLI `nats` e do mecanismo de migração (infraestrutura ainda não definida); skills externas de NATS citadas não foram verificadas.
- SSOT (`docs/SSOT.md`, `docs/POSTGRESQL.md`): validar em ambiente real relay com transporte, failover, PITR, proteção em repouso, *pooling* de conexões (trava consultiva exige sessão) e custo de DDL. Chave de idempotência: definida como cabeçalho HTTP `Idempotency-Key` (LOOP §6.1.1); não é transportada no `requested`, que leva o `operationId` derivado (decisão 0002).
- Quando houver implementação: escolher o formato de schema e registrar a decisão em `.decisions/`; formalizar em `schemas/` o envelope comum, os limites padrão e a família de contratos descrita em `docs/SCHEMA.md`.
- Registrar as primeiras ADRs em `.decisions/` (ex.: NATS JetStream, modelo desired/observed).
- Auditar a consistência entre os quatro documentos de `docs/` e entre eles e `.opencode/`.
