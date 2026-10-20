# 0070 — Senhas dos serviços como arquivos montados em `/run/secrets`

- **Data:** 2026-10-20
- **Status:** Aceita e implementada em dev. Detalha a 0067 (arquivos de segredo); não contradiz o §2 nem o §4 do `AGENTS.md`.

## Contexto

A 0067 fez o código ler `/run/secrets/<VARIÁVEL>`, mas o compose de dev ainda entregava as senhas por variável de ambiente. Variável de ambiente aparece em `docker inspect`, em `/proc/<pid>/environ` e em processos filhos. As especificações (`NATS.md` §18.5, `POSTGRESQL.md` §14.5) exigem gestão de segredos, sem escolher o mecanismo. O §2.5 não deixa a segurança de código e de configuração variar por ambiente; só a de infraestrutura que não existe em dev pode ser lacuna declarada.

## Decisão

- **Formato:** cada senha de papel (`<FEATURE>_<PAPEL>_DATABASE_PASSWORD` e `<FEATURE>_<PAPEL>_MESSAGING_PASSWORD`) chega como arquivo somente leitura em `/run/secrets/<VARIÁVEL>`. O nome do arquivo é o nome completo da variável, o que o `SecretFilesSource` já lê.
- **Menor privilégio (§4.2):** cada papel monta só os segredos que usa.
- **Os manifestos não definem essas variáveis.** O ambiente vence o arquivo (precedência da 0067); uma variável `*_PASSWORD` esquecida anularia o segredo montado.
- **Origem em dev:** o Compose declara `secrets:` com `environment: <VARIÁVEL>`, lendo do `.env` como antes. Nada muda para quem já tem `.env`.
- **Origem em stg e prd:** o cofre de segredos. O cofre (Vault, External Secrets, KMS do provedor) **não está decidido** e não há evidência no repositório para escolhê-lo; fica em aberto até o alvo de execução ser definido.
- **Fora do escopo:** `NATS_PASSWORD` do contêiner `consumer` e `PGPASSWORD` do `migrate` (a CLI `nats` e o `psql` leem variável de ambiente; são contêineres de inicialização), e as senhas da infraestrutura.

## Justificativa

Segurança vence (§2.1): a senha sai do ambiente do processo e do `docker inspect`, ao custo de um bloco `secrets:` por papel. O código e os testes não mudam. O caminho é aditivo (§2.6): o `source` do Compose vira um `Secret` do Kubernetes montado como volume, com os mesmos nomes de arquivo, sem tocar no código.

## Consequências

- Serviço sem o arquivo recusa subir com `missing required configuration` (erro explícito).
- A rotação ainda pede reinício: o serviço lê o segredo na partida.
- Os 3 compose e a semente do template seguem o mesmo bloco; `sync.py --check` valida a semente.
- Pendência para o stg: o cofre e a entrega dos arquivos nele (registrada em `docs/IMPLEMENTATION-STATUS.md` §7.1).
