# Roadmap do Projeto

Este documento define a visão estratégica, os objetivos e o planejamento futuro do Smarkee. Ele organiza as tarefas e ajuda novos contribuidores a entenderem o status atual do projeto e para onde ele está indo.

## ⚠️ Disclaimer
> Este roadmap é um documento vivo ("forward-looking statement"). Os itens e horizontes listados abaixo não são promessas estritas ou garantias contratuais de entrega, mas sim a intenção e as prioridades atuais do projeto, sujeitas a alterações sem aviso prévio conforme as necessidades evoluem.

## 🧭 Visão e Objetivos

O principal objetivo do projeto é construir uma plataforma de arquitetura distribuída e mensageria escalável que adote os mais rigorosos padrões de segurança, observabilidade e idempotência.

## 🗺️ Horizontes de Planejamento

Adotamos a metodologia **Now, Next, Later** para o planejamento. Em vez de datas rígidas (que costumam falhar em projetos dinâmicos e open-source), utilizamos blocos lógicos de prioridade.

### 🟢 Now (Em Andamento / Curto Prazo)
O que está sendo trabalhado ativamente neste momento.
- [ ] **`[In Progress]` Contratos e Mensageria:** Modelagem semântica da troca assíncrona de mensagens e dos schemas de contrato (`docs/messaging/MESSAGING.md`, `docs/messaging/NATS.md` e `docs/data/SCHEMA.md`), já exercitada pelo User.
- [ ] **`[In Progress]` Resource Control Loop:** Modelo de reconciliação entre `desired` e `observed` e sua segurança (`docs/loop/RESOURCE-CONTROL-LOOP.md` e `docs/loop/RESOURCE-CONTROL-SECURITY.md`).
- [ ] **`[In Progress]` Primeira Fatia Vertical (`core`/`user`, `sum`/`service` e `ipm`/`organization` completos):** um projeto e uma imagem por feature, com um contêiner por papel (`api`, `publisher` e, quando há provedor externo, `controller`; decisões 0096 e 0098), com servidor de saúde e testes e2e black-box (incluindo falhas de componentes), validando os contratos especificados (`docs/loop/RESOURCE-CONTROL-LOOP.md`, seção 48).
- [ ] **`[Preview]` Usuários da Organization (`ipm`/`user`):** o dono da Organization cria usuários dentro dela, com roles da plataforma (decisões 0077, 0083 e 0085), API `/v1/ipm/users` e `sk ipm user`. Usuários recebem exclusivamente roles. Toda Organization já nasce preparada para usuários pelo loop (decisão 0081).
- [ ] **`[In Design]` Grupos de Usuários da Organization (`ipm`/`group`):** agrupamentos lógicos de usuários por Organization (`ipm.group`) com atribuição em bloco de roles (decisão 0085).
- [ ] **`[Preview]` Billing Account (`bsm`/`account`):** unidade de cobrança do módulo Billing Service Manager (`bsm`), gerenciada pelo Resource Control Loop (`/v1/bsm/accounts`) e pela CLI `sk bsm account` (fase P0 com estado local reconciliado).
- [ ] **`[In Progress]` SSOT e Persistência:** Modelo e garantias de gravação do SSOT e sua implementação de referência em PostgreSQL com `jsonb` (`docs/data/SSOT.md` e `docs/data/POSTGRESQL.md`).

### 🟡 Next (Próximos Passos / Médio Prazo)
O que está planejado para ser puxado assim que o horizonte "Now" for esvaziado.
- [ ] **`[Planned]` Implantação em Kubernetes:** CI/CD e GitOps por componente, com versão e imagem independentes.
- [ ] **`[Planned]` Encerramento limpo dos componentes:** o Manager do User espera o `drain()` do NATS até o tempo limite (cerca de 30 s) e registra `task stopped unexpectedly` mesmo quando o encerramento foi pedido. O Manager do SUM já usa `close()` e só registra o erro sem pedido de parada; aplicar o mesmo ao User, e revisar os demais componentes que copiaram o padrão.
- [ ] **`[Planned]` Observabilidade Básica:** Métricas de aplicação e spans nos componentes (hoje há logs estruturados com `trace_id` ligado ao trace do gateway, spans do gateway, métricas de contêiner e probes de saúde).
- [ ] **`[Planned]` Endurecimento para stg e prd:** `pinned_client` no Executor, identidades e permissões por papel no NATS, TLS, quarentena de mensagens, retenção do SSOT, `ObservationStale`, limite de remoções e backup com recuperação (lacunas em `docs/platform/IMPLEMENTATION-STATUS.md`).

### 🔴 Later (Exploratório / Longo Prazo)
O que está no radar para o futuro, mas ainda carece de design, arquitetura ou Discovery.
- [ ] **`[Exploratory]` Clusterização Avançada NATS:** Topologia de Hub-Spoke com Leaf Nodes.
- [ ] **`[Exploratory]` Provisionamento por IaC (Terraform):** criar o Zitadel (organizações, projetos, aplicações, contas de serviço) por código, com os IDs como saída que gera a configuração por ambiente (decisão 0037).
- [ ] **`[Exploratory]` Cofre de segredos (OpenBao):** senhas por componente, chaves das contas de serviço e rotação, junto com o ambiente de stg (decisão 0037).
- [ ] **`[Exploratory]` Operador do SUM:** o kill switch e a visão de operador do SUM (decisão 0039). Os papéis de instância do Executor e do Observer da Organization ficam como estão, por exceção deliberada (decisão 0060); a revisão acontece se o Zitadel passar a oferecer um papel padrão menor.
- [ ] **`[Exploratory]` Plataforma de UI:** Dashboard de gestão do estado (`desired` / `observed`).
- [ ] **`[Exploratory]` Exclusão da conta, o que resta (decisões 0039 e 0040):** operador excluir a conta de terceiros (filtro por dono nas listas), estado "excluindo" que feche a janela entre verificar e excluir, dados pessoais em mensagens e no outbox até a retenção, sessões e tokens depois de excluir, e confirmação ou reautenticação.
- [ ] **`[Exploratory]` Administração da plataforma:** ferramentas de operador (roles `*.admin`) para conceder e revogar o acesso de um usuário existente (`platformAccess` e `platformRoles`); o usuário final não altera o próprio acesso.

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
