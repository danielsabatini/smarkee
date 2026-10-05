# Memória Operacional do Projeto (AI Context)

Em conformidade com o `AGENTS.md` (Seção 35.1), este arquivo atua exclusivamente como a **área de transferência de contexto** entre as sessões dos agentes.

## O que o próximo agente precisa saber agora?

*(Este arquivo deve permanecer compacto. Registre aqui apenas o contexto ativo, tarefas em andamento e dependências imediatas. Remova tarefas finalizadas e lixo geracional. **Não** utilize este arquivo como documentação oficial, governança ou registro de regras permanentes).*

### Estado Atual
- Fase de especificação: `docs/` contém `MESSAGING.md`, `NATS.md`, `SCHEMA.md` e `RESOURCE-CONTROL-LOOP.md`. `MESSAGING.md` foi reescrito.
- `docs/RESOURCE-CONTROL-LOOP.md` foi revisado e `docs/RESOURCE-CONTROL-SECURITY.md` criado. O modelo adotado: o Reconciler consome `desired` e `observed` pela mensageria (sem acesso ao SSOT), com um Stream por `messageType` e `desired`/`observed` em operação `changed`.
- Os arquivos em `components/` e `features/` são esqueletos vazios. **Decisão do usuário: não implementar nada por enquanto.**

### Tarefas Pendentes
- Validar em ambiente real (não há broker para testar): configuração dos Streams e das ACLs de JetStream descritas em `docs/NATS.md`, e a população do `AUDIT` a partir de Streams `WorkQueue` (`REQUESTED`, `ACTION`).
- Definir o mecanismo de *single-flight* por `resourceId` para `ACTION` (hoje só o requisito está especificado).
- Registrar as primeiras ADRs em `.decisions/` (ex.: NATS JetStream, modelo desired/observed).
- Auditar a consistência entre os quatro documentos de `docs/` e entre eles e `.opencode/`.
