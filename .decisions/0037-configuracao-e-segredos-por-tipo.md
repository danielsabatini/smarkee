# 0037 — Configuração e segredos por tipo, sem pasta global de configurações

- **Data:** 2026-10-16
- **Status:** Aceita como direção; os três passos abaixo são planejados e **ainda não implementados**.

## Contexto

Surgiu a ideia de reunir as configurações globais (banco, NATS, Zitadel, endereços) em uma pasta na raiz (`settings/`), com pydantic e `Enum`. Medi o que existe hoje:

- **8 arquivos `.env`** (e os `.env.example`), com cerca de 78 variáveis: 4 da infraestrutura (`messaging`, `database`, `gateway`, `identity`), 3 das features (`core/user`, `ipm/organization`, `sum/service`) e o da CLI. Cada componente lê a sua configuração por variáveis `<PREFIXO>_<SEÇÃO>_<CAMPO>` (pydantic-settings, decisão 0017).
- **Nenhum nome de variável se repete.** Repetem-se **valores** sob nomes diferentes: os IDs dos três projetos de roles (na CLI e no `AUTH_AUDIENCE` de cada Receiver), o ID da organização `register` (User e SUM), o host do Postgres (`database`, `gateway`, `identity`) e a senha de dev do NATS (uma variável por componente, todas iguais em dev).
- **O prejuízo real é o desvio**, e não estar em vários arquivos: ao recriar a instância de dev (`docker compose down -v`), os IDs do Zitadel mudam e cerca de cinco lugares precisam ser atualizados à mão. Já tivemos um erro por isso (o `ipm.projectId` ausente na configuração da CLI).

## Decisão

- **Não haverá pasta global de configurações nem pacote pydantic compartilhado.** A CLI é distribuída e carrega os padrões de produção **dentro** dela (decisão 0036); cada componente é autocontido (projeto `uv` e Dockerfile próprios, decisão 0015); um `Enum` de ambientes na CLI reintroduz o `--env` que a decisão 0023 descartou; e uma pasta "global" atrai segredos, enfraquecendo a regra de que IDs e endereços são públicos e senhas não são.
- **A configuração se separa por tipo**, cada tipo com a sua fonte:
  - **Padrões de produção da CLI:** um só lugar, `clients/cli/src/sk/defaults.py`. Dev e stg sempre por variáveis (`.env`).
  - **Valores que nascem do provisionamento** (IDs de projeto e de organização do Zitadel): devem ser **saída da infraestrutura como código**, e não digitados.
  - **Segredos** (senhas, chaves das contas de serviço): um cofre, uma credencial por componente (menor privilégio, `AGENTS.md` §4.2).
  - **Endereços de outros serviços:** DNS e rede interna, como hoje.
- **Plano, nesta ordem:**
  1. **Detector de desvio (barato, implementado em 2026-10-16):** um teste somente leitura em `infrastructure/dev/identity/conformance` que compara os IDs de cada `.env` com os do Zitadel real e aponta o que está desatualizado. Elimina o risco sem centralizar nada.
  2. **Terraform** para o provisionamento do Zitadel: o ID sai como saída, e as configurações por ambiente são geradas a partir dela (e os `.env.example`, o e2e e os padrões da CLI passam a ser derivados, no padrão de `schemas/` com arquivos gerados, `AGENTS.md` §22). Só aqui faz sentido uma fonte por ambiente (`settings/<ambiente>.yaml`, sem segredos).
  3. **OpenBao**, junto com stg, para os **segredos** e a rotação (as chaves das contas de serviço vencem em 2027-10-15). Resolve a senha copiada em cada `.env` e a chave no volume `identity-bootstrap`; para o Postgres, credenciais dinâmicas com validade curta.

## Justificativa

- **Segurança:** segredos e identificadores públicos têm tratamentos opostos; separá-los é o que permite credencial por componente e rotação.
- **Simplicidade:** não se cria uma camada nova (pasta, pacote, `Enum`) para uns oito valores por ambiente. A fonte única por ambiente só se paga quando houver um segundo ambiente ou o Terraform.
- **Robustez:** o detector ataca o risco medido (desvio dos IDs) já, sem depender das peças maiores.
- **Alternativas descartadas:** `settings/` com pacote pydantic compartilhado (quebra a autonomia dos componentes e a distribuição da CLI); colocar os IDs no cofre (esconde um dado público e continua digitado à mão); centralizar as senhas num arquivo (fere o menor privilégio e não serve ao Kubernetes, que injeta ConfigMap e Secret por Deployment).

## Consequências

- **Nada muda hoje no código:** a decisão registra a direção. O `.env` por componente continua sendo o mecanismo de dev.
- **OpenBao não resolve os IDs** (não são segredo) nem elimina a configuração do caminho de cada segredo; resolve a digitação e a rotação dos segredos.
- **Pendências:** os três passos acima (ROADMAP: o detector em Next; o Terraform e o OpenBao em Later). O gatilho do passo 2 é o primeiro ambiente além do dev, ou o Terraform; o do passo 3 é o stg.
- **Não verificado:** o Terraform e o OpenBao não foram avaliados contra a versão do Zitadel (v4.19.4) nem contra o Kubernetes de stg e prd.
