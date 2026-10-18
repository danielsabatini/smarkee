# 0059 — Telemetria no piso: redação na infra, fila persistente, teste de correlação e IP mantido

- **Data:** 2026-10-18
- **Status:** Aceita e implementada em desenvolvimento. Aplica as decisões 0056, 0057 e 0058 à observabilidade.
- **Origem:** a avaliação de observabilidade de 2026-10-18 contra o piso do §2 do `AGENTS.md` e as respostas do responsável aos seis itens do piso.

## Contexto

A avaliação apontou, entre outros pontos, dados sensíveis na telemetria, fila de envio nunca testada sob falha e ausência de um teste que prove a correlação do `trace_id`. Ao executar, cada ponto foi verificado de novo contra os arquivos reais.

## Decisão

1. **Query nos spans: nada a corrigir.** O achado "credencial nos spans" era um **falso positivo do avaliador**: contou `code=` sem olhar o valor. Todos os valores de `url.query` já eram `REDACTED` (79 de 79), e `args` e `http.target` não chegam ao arquivo. A redação já existia (decisão 0050).
2. **Logs de infra (achado real).** O `WARN` "missing translation" do Zitadel despejava e-mail, nome e o código de verificação do usuário (23 registros). O `telemetry-agent` passa a **descartá-lo** e a **trocar qualquer e-mail por `<redacted-email>`** nos logs de infra, como defesa em profundidade. Os logs de componentes seguem fora dessa regra: o contrato 0045 já proíbe valores.
3. **Fila do agente explícita e em disco.** Medição em dev (150 registros, 1 por segundo; o `telemetry-gateway` fora do ar por 60 s): com a fila padrão, em memória, uma queda sozinha não perdeu nada (150 de 150); com o **agente reiniciado durante a queda**, perderam-se 31. Pelo §2.6 (evolução aditiva), acrescentou-se ao exportador existente `sending_queue` com `storage: file_storage` (a extensão que já guardava o checkpoint) e `retry_on_failure` explícito. Repetido o mesmo experimento: 150 de 150, sem duplicatas.
4. **Teste versionado de correlação e privacidade:** `infrastructure/dev/telemetry-gateway/conformance`. Um cadastro pelo gateway deve aparecer com o mesmo `trace_id` do span do gateway em Receiver, Manager, Publisher, Reconciler e Executor; `traceparent` forjado é ignorado; spans sem atributos de URL completos e com query redigida; logs de infra sem e-mail nem código; e a redação do agente provada por um contêiner sintético.
5. **IP do cliente nos spans: mantido**, por decisão do responsável. É dado pessoal; em stg e prd, a retenção curta do backend e a base legal precisam ser definidas antes de o dado ser guardado.
6. **Papéis de instância da Organization: mantidos, por exceção deliberada** (decisão 0060). Existe caminho (papéis customizados em `InternalAuthZ.RolePermissionMappings`), mas o custo é relevante e a evidência é parcial; o responsável decidiu manter, porque o padrão do Zitadel não tem papel menor.

## Justificativa

- **Segurança:** os dados pessoais e o código de verificação deixam de ir para a telemetria; o experimento e a redação são verificados por teste, não por afirmação.
- **Robustez e resiliência:** a fila em disco fecha uma perda medida; o teste impede regressão silenciosa da correlação e da privacidade.
- **Simplicidade e evolução aditiva (§2.6):** nenhum componente novo; a fila persistente reaproveita a extensão e o volume que já existiam.

## Consequências

- A fila em disco ocupa o volume `telemetry-agent-data`, limitada a 1000 lotes; cheia, descarta o dado novo sem bloquear a leitura dos logs.
- O teste de conformidade cria usuários `conf.telemetry-*`, removidos pelo `smarkee-dev-cleanup`.
- Fica registrada a lição do falso positivo: um achado de segurança precisa do **valor** verificado, não só da presença do campo.
