# Roadmap do Projeto

Este documento define a visão estratégica, os objetivos e o planejamento futuro do Smarkee. Ele organiza as tarefas e ajuda novos contribuidores a entenderem o status atual do projeto e para onde ele está indo.

## ⚠️ Disclaimer
> Este roadmap é um documento vivo ("forward-looking statement"). Os itens e horizontes listados abaixo não são promessas estritas ou garantias contratuais de entrega, mas sim a intenção e as prioridades atuais do projeto, sujeitas a alterações sem aviso prévio conforme as necessidades evoluem.

## 🧭 Visão e Objetivos

O principal objetivo do projeto é construir uma plataforma de arquitetura distribuída e mensageria escalável que adote os mais rigorosos padrões de observabilidade, idempotência e governança de Inteligência Artificial.

## 🗺️ Horizontes de Planejamento

Adotamos a metodologia **Now, Next, Later** para o planejamento. Em vez de datas rígidas (que costumam falhar em projetos dinâmicos e open-source), utilizamos blocos lógicos de prioridade.

### 🟢 Now (Em Andamento / Curto Prazo)
O que nossa equipe (humana e IA) está trabalhando ativamente neste exato momento.
- [ ] **`[In Progress]` Governança da IA:** Finalizar a arquitetura fundamental de agentes (`AGENTS.md`) e regras rigorosas de poluição de contexto.
- [ ] **`[In Progress]` Estruturação de Estado:** Definição correta do uso de `MEMORY.md`, `.decisions/`, e separação do ambiente efêmero `.workspace/`.
- [ ] **`[In Design]` Integração NATS:** Modelagem semântica para troca assíncrona de mensagens (`docs/MESSAGING.md` e `docs/NATS.md`).

### 🟡 Next (Próximos Passos / Médio Prazo)
O que está planejado para ser puxado assim que o fluxo de trabalho do horizonte "Now" for esvaziado.
- [ ] **`[Planned]` Templates de Projetos:** Criação de esqueletos iniciais baseados nas SKILLS.
- [ ] **`[Planned]` Observabilidade Básica:** Implementação de traces estruturados nos workers.
- [ ] **`[Planned]` Diretrizes de Contribuição:** Finalização do `CONTRIBUTING.md` para novos membros.

### 🔴 Later (Exploratório / Longo Prazo)
O que está no radar para o futuro, mas ainda carece de design, arquitetura ou Discovery.
- [ ] **`[Exploratory]` Clusterização Avançada NATS:** Topologia de Hub-Spoke com Leaf Nodes.
- [ ] **`[Exploratory]` Plataforma de UI:** Dashboard de gestão do estado (`desired` / `observed`).

## 🏷️ Fases de Lançamento (Status)

Para facilitar a leitura, cada item possui uma etiqueta indicando a sua maturidade:
- `[Exploratory]`: Em fase de pesquisa ou ideação (levantamento de viabilidade).
- `[In Design]`: Sendo arquitetado (gerando ADRs na pasta `.decisions/`).
- `[In Progress]`: Em desenvolvimento ativo.
- `[Preview]`: Disponível em branch de preview / testes beta.
- `[GA]`: Generally Available / Lançado para produção (Neste ponto o item sai do Roadmap e vai para o `CHANGELOG.md`).

## 🤝 Como Contribuir

Quer puxar algum card do horizonte **Next** ou tem uma ideia para o **Later**? 
Consulte nosso [CONTRIBUTING.md](CONTRIBUTING.md) (em breve) para saber como participar ativamente das discussões, propor PRs e alinhar o desenvolvimento com as documentações oficiais.
