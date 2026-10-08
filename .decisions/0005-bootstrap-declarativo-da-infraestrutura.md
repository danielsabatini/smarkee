# 0005 — Bootstrap declarativo da infraestrutura

- **Data:** 2026-10-06
- **Status:** Aceita para desenvolvimento; direção proposta para stg e prd

## Contexto

Cada serviço do ambiente de desenvolvimento (`infrastructure/dev`) aplicava o seu estado inicial de um jeito diferente:

- PostgreSQL: scripts SQL em `initdb/`;
- NATS: um script shell que percorria arquivos JSON;
- Kong: arquivo solto, com um script shell embutido no compose;
- Zitadel: variáveis de ambiente no compose.

Era preciso um padrão único, explícito, sem código próprio para manter, e que servisse de base para stg e prd, que rodarão em Kubernetes.

## Decisão

### Desenvolvimento

- Cada serviço guarda o seu **estado inicial declarado** em `bootstrap/`, com arquivos direto na raiz da pasta, **cada um nomeado pelo que configura**, em **formato nativo** da ferramenta e **sem scripts**.
- A configuração do servidor (`*.conf`) fica fora de `bootstrap/`.

| Serviço | Arquivos | Mecanismo | Quando |
|---|---|---|---|
| database | `kong.sql`, `smarkee.sql`, `zitadel.sql` | `/docker-entrypoint-initdb.d` da imagem | Primeira inicialização do volume |
| identity | Sem pasta: variáveis `ZITADEL_FIRSTINSTANCE_*` no compose | Contêiner `zitadel init zitadel` (schemas internos, só com o usuário `zitadel`) → `start-from-setup` do Zitadel | Primeira inicialização da instância |
| gateway | `routes.yml` | Cadeia de contêineres: `kong migrations bootstrap` → `up` → `finish` → `kong config db_import` | A cada `up` |
| broker | `<stream>.json` | Um contêiner por stream: `nats stream add <NOME> --config` | A cada `up` |

- Os contêineres de inicialização são o equivalente, no Compose, a `initContainers`: serviços de execução única, um comando cada, encadeados por `depends_on` com `service_completed_successfully`.
- **Critério:** o estado inicial é configurado primeiro por variáveis de ambiente ou pela forma mais simples da ferramenta; arquivo em `bootstrap/` é o último recurso, só quando não há alternativa. O Zitadel aceita a primeira instância por variáveis (`ZITADEL_FIRSTINSTANCE_*`) e, por isso, o identity não tem pasta `bootstrap/`. Database (três bancos com donos, localidade e revogações), broker (Streams só pela API) e gateway (rotas só por importação, com banco) não têm alternativa.
- O Zitadel não recebe credencial de administrador do PostgreSQL: banco e usuário vêm de `database/bootstrap/zitadel.sql`, e os schemas internos são criados pelo próprio usuário `zitadel`.
- Um stream com configuração diferente da existente faz o contêiner falhar de forma explícita. A alteração é feita com um `nats stream edit` deliberado.

### Princípios comuns a todos os ambientes

- Fonte declarativa e versionada.
- Os mesmos nomes de streams, bancos, papéis e rotas em todos os ambientes (`docs/NATS.md`, configuração por ambiente).
- Separação entre estado inicial e configuração do servidor.
- Aplicação pela infraestrutura, com identidade administrativa própria (`docs/NATS.md` e `docs/POSTGRESQL.md`).

### Direção para stg e prd (Kubernetes), a confirmar no desenho desses ambientes

- **Reconciliar, e não apenas inicializar:** recursos declarados aplicados por GitOps, com revisão do plano antes de aplicar e detecção de diferenças.
- **NATS:** streams e consumers como CRDs do operador oficial NACK. O conteúdo dos JSON de dev é reaproveitado, com conversão de formato.
- **PostgreSQL:** bancos e papéis por operador de PostgreSQL; o schema do SSOT por migrações versionadas executadas em `Job`.
- **Kong:** migrações em `Job` e configuração declarativa aplicada por ferramenta de sincronização.
- **Zitadel:** as mesmas configurações de primeira instância, por variáveis (por exemplo, valores do chart), com a senha do administrador vinda do gestor de segredos.
- **Segredos:** vindos de gestor de segredos, nunca de arquivo.
- **Identidade:** uma por serviço no NATS (`docs/NATS.md`, exemplos de autorização).
- **Parâmetros por ambiente** (réplicas, `max_age`, limites) em camadas de configuração por ambiente, sobre uma base comum.

## Justificativa

- Formatos e ferramentas nativos eliminam código próprio de inicialização, que precisaria ser mantido e testado.
- Um arquivo por alvo, com o nome do alvo, torna explícito o que cada arquivo configura.
- Um comando por contêiner faz qualquer falha apontar diretamente o que falhou (por exemplo, `broker-bootstrap-observed`).
- O `nats-server` não aceita declarar streams na configuração (`unknown field "streams"`), por isso a criação é pela CLI oficial.
- Em stg e prd não basta inicializar: a infraestrutura precisa de detecção de diferenças, revisão e alterações destrutivas explícitas, que é o mesmo princípio do Resource Control Loop do projeto.

## Consequências

- Todo arquivo novo em `broker/bootstrap/` exige o seu serviço `broker-bootstrap-<stream>` no compose; sem ele, o arquivo é ignorado.
- A pasta é a mesma nos serviços que a usam (database, broker, gateway), mas o momento em que é aplicada difere: database, só na primeira inicialização (como a primeira instância do Zitadel); gateway e broker, a cada `up`. O README de dev documenta isso.
- Até existir o primeiro serviço que dependa dos streams (o Manager), `docker compose up -d --wait` sem nomear serviços interrompe a espera ao ver um `broker-bootstrap-*` terminar (`exited (0)`). A subida em dev usa `docker compose up -d` seguido de `docker compose up -d --wait broker gateway identity identity-login`.
- O desenvolvimento se desvia conscientemente de stg e prd em três pontos: um único usuário no NATS, senhas triviais e inicialização sem reconciliação.
