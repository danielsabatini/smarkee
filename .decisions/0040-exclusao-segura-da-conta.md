# 0040 — Exclusão segura da conta: só sem recursos atrelados

- **Data:** 2026-10-16
- **Status:** Aceita e implementada em dev (verificada pela jornada e2e com a CLI real).

## Contexto

O `DELETE /v1/core/users/{id}` removia o usuário sem olhar o que dependia dele: Organizations de que ele é dono e serviços habilitados no SUM ficariam órfãos. A decisão 0039 registrou a direção ("só exclui se não houver recurso atrelado"); aqui ela é implementada.

## Decisão

- **A conta só é excluída quando nada depende dela:** nenhuma Organization e nenhum serviço habilitado (uma ligação desligada é só histórico). Se houver, a API responde `409 ResourcesAttached`, dizendo quais recursos impedem, e nada é pedido.
- **A regra é do servidor, pelo fluxo normal:** o Receiver do User pergunta a cada módulo o que pertence a quem chama, com o **token do próprio solicitante** (`GET /v1/ipm/organizations` e `GET /v1/sum/services`, por HTTP na rede interna). Não lê o banco de outro módulo, não usa credencial própria neles e cada módulo continua filtrando pelo dono. Na dúvida (módulo indisponível, resposta fora do contrato), a exclusão **não segue** (`503`, repetível); uma recusa `401` ou `403` inesperada vira `409 ResourcesNotVerifiable`.
- **Só a própria conta é verificável.** Os módulos respondem pelo que pertence a quem chama; por isso um operador que tente excluir **outra** conta recebe `409 ResourcesNotVerifiable` até existir um filtro por dono para operadores (ver 0039).
- **Desabilitar o `ipm` também é protegido:** o Receiver do SUM recusa (`409 ResourcesAttached`) enquanto o dono tiver Organizations, perguntando ao Receiver do `ipm` do mesmo jeito. Com isso, "`ipm` desabilitado" quer dizer "sem Organizations", e o User lê o `403` do `ipm` (sem as roles) como "nenhuma Organization". Sem essa garantia a regra travaria: com o `ipm` habilitado a conta é recusada pelo serviço habilitado, e com ele desabilitado o `ipm` não pode ser consultado.
- **Ordem para excluir uma conta:** `sk ipm organization delete`, depois `sk sum service disable --service ipm`, depois `sk register delete --yes`.
- **CLI:** `sk register get` e `sk register delete --yes [--wait]`, sob o mesmo grupo do cadastro (o cadastro sem subcomando segue igual). `delete` lê a `resourceVersion`, exige `--yes` e, com `--wait`, esquece a sessão local.

## Justificativa

- **Segurança:** a regra no servidor vale para qualquer cliente, e não só para a CLI; o token do solicitante é o menor privilégio possível (o User não ganha acesso novo a nada); na dúvida, nega.
- **Simplicidade:** reaproveita as APIs de leitura que já existem, sem contrato novo entre módulos nem acesso cruzado a banco.
- **Alternativas descartadas:** checar só na CLI (orientação, não regra); o User ler as views de `ipm` e `sum` (quebra a autonomia dos componentes, decisão 0015); credencial de serviço do User nos outros módulos (privilégio a mais).

## Consequências

- **Não é atômico:** entre a verificação e a exclusão, a pessoa poderia criar um recurso. A janela é de milissegundos, o token deixa de valer com o usuário removido (até 15 minutos pelo access token já emitido) e o risco fica registrado; fechar exige um estado "excluindo" que os outros módulos respeitem (0039).
- **Acoplamento de runtime:** o Receiver do User passa a depender dos Receivers do `ipm` e do SUM (endereços em `CORE_USER_RECEIVER_PEERS_*`); indisponíveis, a exclusão fica indisponível, e a criação e a leitura não são afetadas.
- Cada novo módulo com recursos de dono precisa entrar na verificação (`transport/peers.py` do User) e, se for um serviço do SUM, na do desabilitar (`transport/dependents.py` do SUM).
- **Fica em aberto (0039):** operador excluir conta de terceiros (filtro por dono nas listas), dados pessoais que sobram em mensagens e no outbox até a retenção, sessões ativas depois da exclusão, confirmação ou reautenticação, e o estado "excluindo".
