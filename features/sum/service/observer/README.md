# sum-service-observer

Observer de `sum.service` (`sum-service-observer`), componente autocontido (decisões 0015 e 0033). Lê o Zitadel só de
leitura e publica `observed`; nunca altera o sistema externo.

## O que faz

- `provider/zitadel.py`: leitura somente de leitura do Zitadel (sem nenhuma escrita), com a conta `sum-service-observer`
  (`ORG_OWNER_VIEWER` na `register`). Lê se o usuário existe e as autorizações nos projetos de roles configurados.
- `domain/`: `observation.py` traduz a leitura para `present` (com as roles do serviço), `absent` (só quando o Zitadel
  confirma que o usuário não existe) ou `unknown` (qualquer falha de leitura, nunca `absent`). `authorization.py` tem os
  tipos da leitura (`Authorization`, `ProviderError`) e `service.py` o catálogo. O domínio não importa o adaptador.
- `message.py`: monta o envelope `observed` validado pelo contrato, no subject `observer.observed.sum.service.<resourceId>.changed`.
- `engine/observer.py`: decide quando observar: quando o `desired` muda de geração, depois de cada `completed` ou `failed`
  (com o `causationId` do resultado) e periodicamente. Para de observar uma ligação desligada cuja remoção convergiu. Um
  `desired` sem dono, serviço ou `lifecycle` válido não é observado.
- `transport/nats.py` e `main.py`: cada instância cria os próprios consumers de estado (`DESIRED` e `RESULT`, nome único por
  execução, `DeliverLastPerSubject`, `inactive_threshold`) e reconstrói o que observar ao iniciar. A observação periódica tem
  jitter.

## Partição

Com várias réplicas, cada uma observa só os recursos em que `hash(resourceId) mod count == index`
(`SUM_SERVICE_OBSERVER_PARTITION_INDEX` e `..._COUNT`; o padrão é uma instância, `0/1`). Índice fora da faixa é recusado ao
iniciar.

## Configuração

`SUM_SERVICE_OBSERVER_<SEÇÃO>_<CAMPO>`. Obrigatórias: `NATS_PASSWORD`, `ZITADEL_REGISTER_ORGANIZATION_ID`,
`ZITADEL_PROJECT_IDS` (JSON módulo → projeto de roles) e `CATALOG_ROLES` (o mesmo catálogo do Manager).

## Verificação

No ar no dev (Compose), no ciclo de ligar e desligar e reiniciando o Observer no meio de uma ligação pendente
(`../tests/e2e`). A leitura de um usuário real com a role e de um identificador inexistente (`absent`) foi verificada no
Zitadel de dev.

## Testes

```bash
uv run pytest     # observação, motor (partição, entrada inválida), consumer de estado, configurações, saúde e logging
uv run ruff check . && uv run pyright
```
