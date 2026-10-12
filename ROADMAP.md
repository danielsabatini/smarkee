# Roadmap do Projeto

Este documento define a visão estratégica, os objetivos e o planejamento futuro do Smarkee. Ele organiza as tarefas e ajuda novos contribuidores a entenderem o status atual do projeto e para onde ele está indo.

## ⚠️ Disclaimer
> Este roadmap é um documento vivo ("forward-looking statement"). Os itens e horizontes listados abaixo não são promessas estritas ou garantias contratuais de entrega, mas sim a intenção e as prioridades atuais do projeto, sujeitas a alterações sem aviso prévio conforme as necessidades evoluem.

## 🧭 Visão e Objetivos

O principal objetivo do projeto é construir uma plataforma de arquitetura distribuída e mensageria escalável que adote os mais rigorosos padrões de observabilidade, idempotência e governança de Inteligência Artificial.

## 🗺️ Horizontes de Planejamento

Adotamos a metodologia **Now, Next, Later** para o planejamento. Em vez de datas rígidas (que costumam falhar em projetos dinâmicos e open-source), utilizamos blocos lógicos de prioridade.

### 🟢 Now (Em Andamento / Curto Prazo)
O que está sendo trabalhado ativamente neste momento.
- [ ] **`[In Design]` Contratos e Mensageria:** Modelagem semântica da troca assíncrona de mensagens e dos schemas de contrato (`docs/MESSAGING.md`, `docs/NATS.md` e `docs/SCHEMA.md`).
- [ ] **`[In Design]` Resource Control Loop:** Modelo de reconciliação entre `desired` e `observed` e sua segurança (`docs/RESOURCE-CONTROL-LOOP.md` e `docs/RESOURCE-CONTROL-SECURITY.md`).
- [ ] **`[In Progress]` Primeira Fatia Vertical (`core`/`user` completo e `ipm`/`organization` em andamento):** componentes autocontidos por papel (`receiver`, `manager`, `publisher`, `observer`, `reconciler` e `executor`), com servidor de saúde, partição do `ACTION` e testes e2e black-box (incluindo falhas de componentes), validando os contratos especificados (`docs/RESOURCE-CONTROL-LOOP.md`, seção 48).
- [ ] **`[In Design]` SSOT e Persistência:** Modelo e garantias de gravação do SSOT e sua implementação de referência em PostgreSQL com `jsonb` (`docs/SSOT.md` e `docs/POSTGRESQL.md`).

### 🟡 Next (Próximos Passos / Médio Prazo)
O que está planejado para ser puxado assim que o horizonte "Now" for esvaziado.
- [ ] **`[Planned]` Organization derivada do User:** Manager `observed`/`result`, Reconciler, Observer e Executor do tipo `organization` do módulo `ipm`, na estrutura e com o servidor de saúde do User (modelo das demais features), fechando o loop sobre o Zitadel.
- [ ] **`[Planned]` CLI do cadastro:** `sk register`, `sk user get|delete` e `sk ipm organization`, sobre o Receiver do User.
- [ ] **`[Planned]` Implantação em Kubernetes:** CI/CD e GitOps por componente, com versão e imagem independentes.
- [ ] **`[Planned]` Observabilidade Básica:** Implementação de traces estruturados nos workers.

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
Consulte nosso [CONTRIBUTING.md](CONTRIBUTING.md) para saber como participar ativamente das discussões, propor PRs e alinhar o desenvolvimento com as documentações oficiais.
