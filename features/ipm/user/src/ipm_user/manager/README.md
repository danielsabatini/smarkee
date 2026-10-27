# ipm-user-manager

Manager de `ipm.user` (`ipm-user-manager`), um dos quatro papéis da imagem única `ipm-user` (decisão 0063), com processo e contêiner próprios. Veja o [README da feature](../../../README.md).

Admite os pedidos no SSOT do tipo (só insere no outbox; quem o publica é o Publisher): consome `requested` e os catálogos `DESIRED` de permission, role e group, e aplica cada mensagem em uma unidade atômica (linha bloqueada, Operation única, `desired` no outbox), confirmando ao transporte depois do `COMMIT`. Não consome `observed` nem resultados de ação: o estado observado, a fase e a conclusão das Operations são do [Controller](../controller/README.md) (decisão 0096), cujo papel de banco é quem os atualiza. O código das migrações (`migrations/`) é deste projeto; a execução é uma etapa de implantação com o papel administrativo.

Regras próprias do usuário da Organization (decisão 0077), aplicadas na mesma unidade atômica: o e-mail é único dentro da Organization (trava consultiva por Organization e e-mail); só roles do módulo `ipm`; a cota de usuários por Organization (`organizationQuotaLimit`, decidida pelo Receiver; o operador não tem cota) é conferida sob trava consultiva por Organization. O usuário nasce desprotegido; ao remover, o `desired` perde os dados pessoais.

`uv run datamodel-codegen` regera `common/contracts/generated.py` a partir de `schemas/` (o teste de contrato falha se divergir).

## Estrutura

```text
src/ipm_user/manager/
  domain/      regras do usuário da Organization, puras (política e decisão do pedido)
  handlers/    uma unidade atômica por mensagem; portas do SSOT em ports.py
  store/       único código com SQL do SSOT (SsotStore)
  transport/   adaptadores NATS (consumers de `requested` e dos catálogos `DESIRED`)
  main.py
```

A dependência vai em um sentido só (`main → handlers → domain`); `tests/common/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador.

## Saúde

`GET /health/live`, `/health/ready` e `/health/startup` na porta `8000` (`IPM_USER_MANAGER_HEALTH_PORT`). A liveness não consulta dependências; a readiness inclui o NATS.

## Configuração

Variáveis de ambiente `IPM_USER_MANAGER_<SEÇÃO>_<CAMPO>` e o `config.toml` da feature. Obrigatórias, sem default: `IPM_USER_MANAGER_DATABASE_PASSWORD`, `IPM_USER_MANAGER_MESSAGING_PASSWORD`. Os demais valores e defaults estão em `src/ipm_user/manager/settings.py`.

## Desenvolvimento

```bash
# Na raiz da feature (features/ipm/user), que é o projeto único:
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest tests/manager  # os testes de integração exigem a stack de dev e são pulados sem ela
```

**Atenção em dev:** os testes de integração gravam no SSOT de dev usuários de teste em Organizations fictícias (`org-*`, que não existem no Zitadel). Com o Publisher e o loop no ar, as mensagens chegam ao Controller, que não encontra a organização e marca a fase `Failed`; o teste apaga as linhas ao final. Para não gerar esse ruído, pare o Publisher (`docker compose stop ipm-user-publisher`) enquanto eles rodam, ou limpe com `scripts/dev/cleanup` (`uv run smarkee-dev-cleanup --apply`).

Imagem: o `Dockerfile` da feature (imagem única; este papel roda com `command: ipm-user-manager`). O contrato é verificado pelos testes e2e em `../../../tests/e2e`. A publicação do outbox é do Publisher ([`../publisher`](../publisher/README.md)).
