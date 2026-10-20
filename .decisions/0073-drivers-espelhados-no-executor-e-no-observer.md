# 0073 — Drivers espelhados no Executor (escrita) e no Observer (leitura)

- **Data:** 2026-10-20
- **Status:** Aceita e implementada em `ipm.organization`, `core.account` e `sum.service`. Detalha a estrutura interna da decisão 0017 para o Executor e o Observer. Aplica a decisão 0071 (referência de mercado).
- **Origem:** pedido do responsável pelo projeto: o Executor é o worker que toca o recurso real e deve ser estruturado em `drivers/`, pequenas porções de código que executam uma ação específica num sub-recurso (organização, usuário, metadado, role); o Observer espelha a mesma estrutura, só lendo.

## Contexto

Cada papel tinha um cliente único por provedor (`provider/identity.py`: `IdentityWriter`, `IdentityReader`, `IdentityGranter`) que misturava três coisas: a conexão autenticada (token da conta de serviço, HTTP, classificação de erros), as operações de **vários** sub-recursos (na Account, usuário e autorização no mesmo arquivo) e constantes do provedor. Consequências:

- o código de autorização (grants) estava quase igual em `core/account` e `sum/service`;
- um sub-recurso novo compartilhado (o metadado, para organização e usuário) nasceria duplicado;
- o Executor e o Observer do mesmo sub-recurso não tinham correspondência visível.

## Referência de mercado

Os provedores do Crossplane implementam um cliente por tipo de recurso gerenciado (`Observe`, `Create`, `Update`, `Delete`) sobre uma conexão com o provedor, e os providers do Terraform implementam cada tipo de recurso (CRUD) sobre um cliente compartilhado. Essas referências vêm do conhecimento da equipe e não foram conferidas na documentação oficial nesta decisão. **Divergência:** aqui leitura e escrita ficam em papéis e credenciais separados (Observer e Executor, menor privilégio, `RESOURCE-CONTROL-SECURITY.md`), então o driver de cada sub-recurso existe em dois lados espelhados, e não num cliente só.

## Decisão

```text
executor/                                  observer/
  engine/      consome a action            engine/      decide quando observar
  actions/     compõe drivers por operação domain/      observation.py compõe drivers
  drivers/     escrita, um por sub-recurso drivers/     leitura, um por sub-recurso
  provider/    conexão de escrita          provider/    conexão só de leitura
```

- **`provider/identity.py` é só a conexão** (`IdentityConnection`): token da conta de serviço, chamada HTTP e classificação dos erros em `ProviderError`. Não conhece recurso.
- **`drivers/<sub-recurso>.py`**: um driver por sub-recurso do provedor (`organization`, `user`, `authorization`; o próximo é `metadata`). Cada driver:
  - tem uma responsabilidade (um sub-recurso) e recebe a conexão (e a configuração de que precisa) por injeção;
  - no Executor, só escreve, com operações pequenas e idempotentes (repetir é sucesso);
  - no Observer, só lê, e erro de leitura nunca vira ausência;
  - não decide **o que** fazer: isso é do Reconciler e das `actions/`.
- **Espelho:** o mesmo sub-recurso tem o mesmo nome de arquivo nos dois papéis (`executor/drivers/user.py` escreve, `observer/drivers/user.py` lê).
- **Composição explícita:** as `actions/` do Executor e o `domain/observation.py` do Observer recebem um pacote `Drivers` (dataclass com um campo por driver, tipado por `Protocol`). O `main.py` monta a conexão e os drivers; o motor só repassa o pacote.
- **Isolamento mantido:** os drivers de cada papel ficam no próprio papel. Um papel não importa outro (`test_role_isolation`), e o `domain/` não importa adaptador (`test_domain_isolation`).

## Justificativa

- **Segurança:** cada papel continua com a própria credencial; a conexão do Observer não tem caminho de escrita.
- **Simplicidade:** unidades pequenas, cada uma testável com uma conexão falsa; o `provider/` deixa de crescer a cada sub-recurso.
- **Robustez:** a leitura de autorizações do Observer deixou de aceitar um 404 como resposta válida. Antes, um 404 com detalhe virava lista vazia (roles `revoked`); agora só a leitura do usuário aceita o 404 inequívoco como ausência, e o resto é `unknown`.

## Consequências

- Sem mudança de comportamento externo, de contrato ou de configuração: a suíte das três features e os e2e (com caos) seguem verdes.
- `executor/domain/identity.py` passa a existir também no `sum.service` (`ProviderError` e `Grant` saem do `provider/`).
- **Duplicação que continua:** o driver de autorização do Executor é quase igual em `core/account` e `sum/service`. Levá-lo ao template (perfil opcional, decisão 0064) fica para quando houver o terceiro uso ou a decisão sobre extrair os motores.
- O driver de metadado (`deletionProtection` no Zitadel) é o próximo passo e segue esta estrutura.
