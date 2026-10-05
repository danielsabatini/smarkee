---
name: PostgreSQL
description: Guia de procedimentos para implementar, migrar, validar, inspecionar e diagnosticar o SSOT em PostgreSQL com jsonb, conforme docs/SSOT.md e docs/POSTGRESQL.md. Use ao adicionar um tipo de recurso, alterar o modelo, revisar privilégios, validar DDL ou diagnosticar outbox, bloqueios e conflitos.
---

# PostgreSQL

## 1. Papel desta skill

Esta skill é um **guia de procedimentos** que chama ferramentas (`psql`, contêiner descartável, leitura de arquivos, pipeline de migração da infraestrutura). Ela não define regras.

```text
AGENTS.md
    ↓
docs/SSOT.md          → modelo e garantias (agnóstico)
    ↓
docs/POSTGRESQL.md    → implementação em PostgreSQL com jsonb
    ↓
esta skill            → procedimento
```

Não redefina aqui colunas, restrições, privilégios, relay ou retenção: leia `docs/POSTGRESQL.md`. Em conflito, os documentos prevalecem.

Para decidir **o que modelar**, use o agent `ssot`. Esta skill cuida de **como implementar e validar** no PostgreSQL.

## 2. Regras de operação

1. **Leitura por padrão.** Inspeção e diagnóstico usam um papel de **somente leitura**.
2. **DDL só por migração da infraestrutura.** O agente prepara e revisa a migração; a aplicação ocorre pelo mecanismo de migração definido pela infraestrutura, com o proprietário dos objetos. Serviços de runtime e esta skill não executam DDL em ambientes compartilhados.
3. **Validação em contêiner descartável**, nunca em ambiente compartilhado, e sem dados reais.
4. **Imagem fixada e aprovada.** Use a versão do PostgreSQL pinada no ambiente (`docs/POSTGRESQL.md`, versão). **Verifique se a imagem existe localmente antes de executar** (`docker image inspect <imagem>`). Se for preciso baixá-la, **peça aprovação antes**: a listagem de imagens pode não refletir o que o `run` precisará baixar.
5. **Credenciais** por arquivo de senha, serviço de conexão ou variável de ambiente do ambiente. Nunca na linha de comando, em log, em arquivo versionado ou na resposta.
6. **Operações destrutivas** (`DROP`, `TRUNCATE`, `DELETE` sem filtro, restauração) exigem confirmação explícita do operador e um ponto de retorno (backup validado).
7. **Dados `confidential`** (`docs/SCHEMA.md`) não são exibidos: ao inspecionar, selecione colunas de controle, e não o conteúdo de `desired` e `observed`.
8. **Não invente** nomes de bancos, schemas, papéis, ferramentas de migração ou versões. Se não existirem, informe e pare.

## 3. Procedimento A: adicionar um tipo de recurso

Entradas: módulo, tipo e o contrato do recurso (`docs/SCHEMA.md`, parâmetros e anotações).

1. Ler `docs/SSOT.md` (modelo, dicionário, invariantes) e `docs/POSTGRESQL.md` (mapeamento e DDL de referência).
2. Confirmar que o contrato do recurso define limites, sensibilidade e os parâmetros do loop. Se não definir, parar e devolver ao agent `ssot`.
3. **Gerar** as quatro tabelas (`<tipo>`, `<tipo>_operation`, `<tipo>_outbox`, `<tipo>_inbox`) **a partir do modelo único** do projeto. Não escreva o DDL à mão por tipo e não edite a tabela gerada (`AGENTS.md`, arquivos gerados). Se o modelo ainda não existir, proponha-o como artefato versionado e pare.
4. Gerar os papéis e os `GRANT` da matriz de `docs/POSTGRESQL.md` (por serviço) e conferir contra a matriz de identidades de `docs/RESOURCE-CONTROL-SECURITY.md`.
5. Executar o Procedimento C (validação em contêiner) com o DDL gerado.
6. Entregar a migração para revisão. Não aplique.

## 4. Procedimento B: alterar o modelo (migração)

1. Classificar a mudança conforme `docs/SCHEMA.md`: compatível (`MINOR`) ou incompatível (`MAJOR`).
2. Planejar em três fases (`docs/POSTGRESQL.md`, migrações): **expandir** (adicionar de forma compatível), **migrar** o conteúdo e a mensagem retida (republicando com a mesma geração e o mesmo conteúdo) e só então **contrair**.
3. Avaliar o bloqueio: DDL que reescreve a tabela inteira ou exige bloqueio longo é um risco. Anote como a mudança evitará bloqueio prolongado.
4. Definir a conversão na leitura durante a coexistência, e como identificar o que ainda está na versão antiga (`schema_version`).
5. Executar o Procedimento C com o estado anterior e o posterior da migração, incluindo os dados de teste da versão antiga.
6. Entregar a migração e o plano de reversão para revisão. Não aplique.

## 5. Procedimento C: validar em contêiner descartável

1. Verificar a imagem fixada: `docker image inspect <imagem>`. Se faltar, **pedir aprovação** para baixá-la.
2. Subir um cluster descartável e isolado (`docker run --rm`), sem rede externa e sem volumes do host além do necessário para ler os scripts. Algumas imagens não trazem inicialização automática; nesse caso inicialize o cluster dentro do contêiner e use um diretório de socket gravável.
3. Aplicar o DDL e os `GRANT` com `psql -X -v ON_ERROR_STOP=1 -f <arquivo>`.
4. Executar os testes funcionais do que foi alterado. O conjunto de verificações de referência está em `docs/POSTGRESQL.md` (verificação do DDL): restrições, concorrência otimista e geração, monotonia de `observed_at`, duplicata do inbox, índice de idempotência, privilégios por papel (incluindo as negações), ordem do outbox com duas sessões, trava consultiva.
5. Executar os **casos negativos** (devem falhar): identificador inválido, `jsonb` que não é objeto, fase inválida, escrita sem privilégio.
6. Remover o contêiner e qualquer arquivo temporário (`--rm`; scripts em `.workspace/`).
7. Reportar o que foi e o que **não** foi verificado (carga, failover, PITR, proteção em repouso, *pooling*).

## 6. Procedimento D: inspecionar (somente leitura)

Use `psql -X` com papel de leitura. Perguntas e consultas de referência:

| Pergunta | Consulta |
|---|---|
| Atraso do relay | `SELECT now() - min(created_at) FROM <schema>.<tipo>_outbox WHERE published_at IS NULL;` |
| Quantidade pendente | `SELECT count(*) FROM <schema>.<tipo>_outbox WHERE published_at IS NULL;` |
| Recursos por fase | `SELECT phase, count(*) FROM <schema>.<tipo> GROUP BY phase;` |
| Recursos suspensos | `SELECT count(*) FROM <schema>.<tipo> WHERE reconciliation = 'suspended';` |
| Observação envelhecida | `SELECT count(*) FROM <schema>.<tipo> WHERE observed_at < now() - $intervalo;` |
| Tamanho das tabelas | `SELECT pg_size_pretty(pg_total_relation_size('<schema>.<tabela>'));` |
| Bloqueios em espera | `SELECT pid, wait_event_type, wait_event, state, left(query, 80) FROM pg_stat_activity WHERE wait_event_type = 'Lock';` |
| Privilégios efetivos | `\dp <schema>.*` e `SELECT has_table_privilege('<papel>', '<schema>.<tabela>', 'DELETE');` |

Evite `SELECT *` e qualquer exibição do conteúdo de `desired` e `observed`.

## 7. Procedimento E: revisar segurança

1. Conferir os papéis e os `GRANT` contra a matriz de `docs/POSTGRESQL.md` e de `docs/RESOURCE-CONTROL-SECURITY.md`: um papel por serviço; Manager sem `DELETE` em outbox, inbox e operation; API só com leitura por coluna; relay só com `UPDATE (published_at)`; manutenção separada.
2. Confirmar que `PUBLIC` não possui privilégios no schema nem nas tabelas.
3. Confirmar que nenhum serviço de runtime é proprietário de objeto nem executa DDL.
4. Confirmar TLS fora do ambiente local, proteção em repouso (validada no ambiente) e que log não registra parâmetros nem colunas `confidential`.

## 8. Procedimento F: diagnosticar

| Sintoma | Verificar | Observação |
|---|---|---|
| Atraso crescente no outbox | Procedimento D (atraso e pendentes); o relay está ativo e com a trava consultiva? | Uma única instância ativa por tabela. Não "acelerar" com `SKIP LOCKED` |
| Mensagens fora de ordem | Se a transação atualiza a linha do recurso antes de inserir no outbox; se há mais de um relay | A ordem por recurso depende dessa sequência e de uma única instância |
| Mensagem publicada duas vezes | Falha entre publicar e marcar `published_at` | Esperado (entrega pelo menos uma vez); a deduplicação do transporte e a idempotência dos consumidores absorvem |
| Mensagens perdidas pelo relay | Uso de marca-d'água por `sequence` | O relay seleciona por `published_at IS NULL` |
| Muitos conflitos de atualização | Taxa de linhas afetadas igual a zero | Versão desatualizada informada pelo solicitante; é esperado em concorrência |
| Espera por bloqueio | Bloqueios em espera (Procedimento D); documentos grandes | Toda atualização bloqueia a linha inteira |
| Geração incrementando sem mudança de especificação | A comparação de `desired` na atualização | Mudar só `reconciliation` não incrementa a geração |
| Falhas de serialização ou deadlock | Nível de isolamento e ordem de acesso | Read Committed é o padrão; a aplicação repete a unidade |
| Trava consultiva não obtida | *Pooling* de conexões | A trava é de sessão e não funciona com *pooling* de transação |

## 9. Critérios de conclusão

Registre cada item como `PASS`, `FAIL` ou `NOT VERIFIED` (com o motivo). Não transforme item não executado em sucesso.

```text
PostgreSQL

Modelo gerado do modelo único:             PASS/FAIL/NOT VERIFIED
Restrições (CHECK, tamanho, formato):      PASS/FAIL/NOT VERIFIED
Concorrência otimista e geração:           PASS/FAIL/NOT VERIFIED
Idempotência de entrada:                   PASS/FAIL/NOT VERIFIED
Outbox (atomicidade, ordem, relay):        PASS/FAIL/NOT VERIFIED
Privilégios (menor privilégio, negações):  PASS/FAIL/NOT VERIFIED
Migração (expandir, migrar, contrair):     PASS/FAIL/NOT VERIFIED
Recuperação (PITR, teste de restauração):  PASS/FAIL/NOT VERIFIED
Observabilidade:                           PASS/FAIL/NOT VERIFIED

Overall: PASS/FAIL
```

## 10. Regra final

```text
modelo e garantias (SSOT.md)
        ↓
implementação em PostgreSQL (POSTGRESQL.md)
        ↓
migração gerada e revisada
        ↓
validação em contêiner descartável
        ↓
aplicação pela infraestrutura
```

Nunca inverter a ordem criando o modelo a partir da conveniência do banco.
