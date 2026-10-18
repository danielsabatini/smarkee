# 0049 — Gateway: Apache APISIX no lugar do Kong

- **Data:** 2026-10-17
- **Status:** Aceita e implementada em desenvolvimento (`infrastructure/dev/gateway`). Para stg e prd é direção a confirmar no desenho desses ambientes. Substitui a parte do gateway da decisão 0005 (a cadeia de migrações e `db_import` do Kong).
- **Numeração:** a 0047 e a 0048 estão reservadas (pipeline e auditoria de logs, decisão 0045).

## Contexto

O gateway era o Kong OSS 3.9.3 com PostgreSQL. A validação de JWT no gateway foi adiada porque o Kong OSS não a cobre: o plugin `jwt` valida a assinatura, mas não valida `aud` nem roles, e escolhe a chave pelo `iss` (o JWKS do Zitadel tem duas chaves ativas). O plugin `openid-connect` do Kong é Enterprise. Além disso, a última tag do Kong no Docker Hub é a `3.9.4` (verificado em 2026-10-17); relatos da comunidade apontam o fim das versões OSS posteriores, sem anúncio oficial verificado.

Uma PoC (2026-10-17, APISIX 3.19.0 contra o Zitadel de dev) mostrou que o plugin `openid-connect` do APISIX valida a assinatura pelo JWKS escolhendo a chave por `kid`, o emissor, a audiência, a expiração e, por rota, qualquer claim por JSON Schema (`claim_schema`), o que cobre as roles.

## Decisão

- **Gateway:** Apache APISIX `3.19.0` (imagem `apache/apisix:3.19.0-debian`), no modo **tradicional**, com a configuração no **etcd** (`quay.io/coreos/etcd:v3.7.2`, um nó, volume `gateway-etcd-data`).
- **Versão do etcd:** a `v3.7.2` (a estável mais nova em 2026-10-17; a linha 3.6 está na 3.6.15). O APISIX exige no mínimo o etcd 3.4.0 e a CI dele só testa com a 3.5.4, então a 3.6 e a 3.7 estão fora da matriz oficial e a compatibilidade foi medida: a 3.7.2 com o APISIX 3.19.0 passou na checagem de versão, no `adc sync`, na propagação por *watch* (~0,3 s para criar e remover rotas), na reconexão após 10 s de queda, na compactação do histórico, na persistência após reiniciar o APISIX, na atualização no lugar de um volume da 3.6.15 (cópia do volume de dev) e em um cluster de 3 nós com perda de um nó e de quórum. Rever a versão a cada atualização do APISIX ou do etcd.
- **Console web:** o console embutido do APISIX (`enable_admin_ui`, em `http://localhost:9180/ui`). Ele funciona sobre a Admin API, que só existe com o etcd; por isso o modo sem etcd (arquivo `apisix.yaml`, validado na PoC) não foi adotado.
- **Estado declarado:** `infrastructure/dev/gateway/bootstrap/adc.yaml`, no formato do ADC (`api7/adc:0.31.0`, Apache-2.0), aplicado pelo contêiner `gateway-sync` (`adc sync`) a cada `up`, depois que o `gateway` fica saudável. Substitui a cadeia `gateway-migrations-*` e `gateway-import` do Kong.
- **Admin API e console:** exigem a chave `APISIX_ADMIN_KEY` (sem padrão, em `gateway/.env`), publicados só em `127.0.0.1:9180`.
- **Contratos preservados:** serviço `gateway`, contêiner `gateway.smarkee.internal`, proxy interno em `:8000` (os Receivers buscam o JWKS ali) e publicado em `:8080`, os hosts, os caminhos (`/v1/<módulo>/<tipos>` e subcaminhos, decisão 0030) e o limite de 10 cadastros por minuto por IP, com `429` e `Retry-After`.
- **Validação de JWT no gateway:** a PoC a desbloqueia, mas **não é habilitada por esta decisão**. Ela foi habilitada pela decisão `0052`; os Receivers seguem validando `aud` e roles.

## Justificativa

- **Segurança:** o gateway passa a poder validar assinatura, audiência e roles; a linha de produto tem versões mantidas; a Admin API exige chave e o cabeçalho `Server` não revela a versão.
- **Simplicidade:** sai o banco `gateway` no PostgreSQL (papel, `gateway.sql`, backup) e saem os quatro contêineres de migração do Kong; entram o etcd e o `gateway-sync`. É o custo do console web.
- **Robustez e disponibilidade:** o estado é declarado e reaplicável; o APISIX volta a resolver o nome de um Receiver recriado em poucos segundos (o Kong guardava o IP antigo por cerca de 10 minutos); com o IdP fora do ar, tokens já conhecidos continuam válidos e a partida a frio falha fechada.
- **Alternativas:** (a) APISIX sem etcd, por arquivo, sem console: mais simples e sem estado, descartada em dev pelo console; reconsiderar para stg e prd; (b) permanecer no Kong OSS: não resolve a validação de JWT; (c) Kong Enterprise: licença comercial.

## Consequências

- **Contratos de desenvolvimento alterados:** a Admin API sai da `8001` sem autenticação para a `9180` com chave; o Kong Manager (`8002`) é substituído pelo console em `9180/ui`; o proxy HTTPS (`8443`) deixa de existir em dev; as variáveis `KONG_*` viram `APISIX_*`. O corpo do `429` agora é HTML (o contrato é o status e o `Retry-After`).
- **Subida:** `gateway-sync` é um contêiner de inicialização; `docker compose up -d --wait` com ele nomeado sai com erro (mesma regra do broker). Use `up -d` e, depois, `up -d --wait` nos serviços de longa duração.
- **Corrida ao recriar o etcd:** logo depois de o etcd ser recriado, o APISIX leva alguns segundos para voltar a enxergá-lo e o primeiro `adc sync` falha com `503`; o `gateway-sync` tenta até 5 vezes (`restart: on-failure:5`) e convergiu na 4ª tentativa no teste.
- **Reconciliação parcial:** o ADC cria, atualiza e **remove** serviços e as rotas de dentro deles, mas não toca em rotas soltas (sem serviço), que é como o console as cria. Elas ficam só no etcd.
- **Banco `gateway`:** o `gateway.sql` foi removido e o backup deixou de incluir o banco `gateway`. O banco e o papel de um volume existente do PostgreSQL permanecem até serem removidos à mão (operação destrutiva, não executada).
- **Riscos aceitos, a revisar:**
  - o backend do APISIX no ADC é declarado experimental e a lista de versões testadas vai até a 3.17; a 3.19 funcionou nos testes de dev;
  - o `kid` desconhecido provoca uma busca do JWKS por requisição (sem cache negativo) e o `limit-count` roda depois do `openid-connect`, então esse plugin não limita o caso;
  - o `401` por role ausente revela o nome da role na mensagem;
  - o limite de taxa usa o IP do par TCP; atrás de balanceador será preciso o plugin `real-ip` (resolvido na decisão 0054);
  - o etcd não tem autenticação nem TLS em dev, e a Admin API aceita conexões de toda a rede `internal` (com a chave);
  - o `etcd` em stg e prd exige autenticação, TLS e backup.
- **Documentação:** `infrastructure/dev/README.md`, os READMEs das features, o backup, os diagramas do fluxo de `core.account` e o CHANGELOG foram atualizados.
