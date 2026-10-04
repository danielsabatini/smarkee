# Memória Operacional do Projeto (AI Context)

Em conformidade com o `AGENTS.md` (Seção 35.1), este arquivo atua exclusivamente como a **área de transferência de contexto** entre as sessões dos agentes.

## O que o próximo agente precisa saber agora?

*(Este arquivo deve permanecer compacto. Registre aqui apenas o contexto ativo, tarefas em andamento e dependências imediatas. Remova tarefas finalizadas e lixo geracional. **Não** utilize este arquivo como documentação oficial, governança ou registro de regras permanentes).*

### Estado Atual
- Estruturação do projeto em andamento.
- Políticas fundamentais de agentes (`AGENTS.md`) foram revisadas e atualizadas para definir regras estritas de Fonte Única da Verdade (SSOT), isolamento de arquivos temporários (`.workspace/`), diretório de decisões (`.decisions/`) e separação de contexto (`MEMORY.md` vs `.journal/`).

### Tarefas Pendentes
- Iniciar a implementação ou arquitetura de domínio conforme especificações em `docs/MESSAGING.md` e `docs/NATS.md`.
