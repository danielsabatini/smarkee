# 0046 — Código idêntico entre componentes é gerado de uma fonte única e conferido

- **Data:** 2026-10-16
- **Status:** Aceita e implementada para o formatter de logs. A fonte e o `sync.py` passaram para `templates/feature/` na decisão 0064. Ajusta a 0015 (duplicação aceita): a duplicação continua, mas passa a ter fonte e verificação. Não decide se os componentes serão juntados ou separados (decisão futura, após a auditoria entre módulos).

## Contexto

A 0015 manteve os componentes autocontidos e aceitou reescrever em cada um o que é comum (logging, saúde, configuração). Com a decisão 0045 (contrato de logs OpenTelemetry), o `logging_config.py` ficou **idêntico nos 18 componentes** de `core.account`, `ipm.organization` e `sum.service`, e mudar o contrato exigiu alterar mais de 100 arquivos. Sem uma fonte, as cópias podem divergir sem que ninguém perceba. Outros arquivos já são idênticos ou quase (`http/health.py` em 16 projetos).

## Decisão

- **O schema da linha de log** (`schemas/observability/log-record.v1.schema.json`, mais o exemplo) é o contrato verificável e neutro de linguagem. O teste de cada componente valida contra ele as linhas que o formatter emite, e restringe os nomes de atributo dos loggers aos que o schema aceita.
- **O código idêntico tem uma fonte única** em `schemas/observability/python/` (`logging_config.py` e `test_logging.py`, este com o marcador `PKG` no lugar do nome do pacote).
- **Cada componente continua com a sua cópia**, sem dependência de runtime entre componentes nem biblioteca interna (a 0015 se mantém).
- **`schemas/observability/sync.py`** (só biblioteca padrão) grava as cópias (`python schemas/observability/sync.py`) ou as confere (`--check`). Um teste em `schemas/tests` falha se qualquer cópia divergir da fonte.
- Para alterar o formatter: altera a fonte, roda o `sync.py`, roda a suíte de cada componente (`AGENTS.md` §22: fonte, geração, verificação).

## Justificativa

| Opção | Segurança | Simplicidade | Robustez |
|---|---|---|---|
| Cópia manual (antes) | Cópias podem divergir e deixar passar um log fora do contrato | Nenhum mecanismo | Divergência silenciosa |
| **Fonte única, cópias geradas e conferidas (adotada)** | Divergência vira falha de teste | Um script e um teste, sem dependência nova | Componentes seguem independentes e podem mudar de linguagem |
| Pacote Python compartilhado | Uma só implementação | Muda o build das imagens (o contexto é a pasta do componente) e os 18 `uv.lock` | Acopla os componentes a uma linguagem e a uma versão; contradiz a 0015 |

O mesmo padrão já existe para os modelos gerados dos contratos (decisão 0012): fonte em `schemas/`, cópia no componente, teste que falha na diferença.

## Consequências

- Os componentes que não tinham `jsonschema` no grupo de desenvolvimento (os Publishers de `core.account` e `ipm.organization`) passaram a tê-lo, porque o teste valida o schema.
- Um componente novo precisa estar em `features/<módulo>/<tipo>/<papel>/` para o `sync.py` encontrá-lo.
- O mecanismo serve a qualquer resultado da auditoria futura: se os papéis forem juntados, a fonte vira o runtime comum; se continuarem separados, ela continua gerando as cópias.
- Outros arquivos idênticos (por exemplo `http/health.py`) podem entrar no mesmo mecanismo depois; ficam fora desta decisão.
