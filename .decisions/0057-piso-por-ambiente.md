# 0057 — Piso dos pilares por ambiente

- **Data:** 2026-10-18
- **Status:** Aceita e aplicada ao `AGENTS.md` (§2.5). Estende a decisão 0056.
- **Origem:** a avaliação de observabilidade de 2026-10-18, feita com o §2 recém-criado, mostrou que parte do que o repositório já fazia em dev (etcd sem autenticação, `http` na rede interna, OTLP sem TLS, agente de telemetria como root) seria violação do piso se a segurança valesse integralmente em dev, e que robustez e resiliência de infraestrutura não precisam ter o mesmo nível em dev e em prd.

## Contexto

O §2.3 diz que nenhum pilar é adiado para uma etapa futura. Sem uma distinção por ambiente, isso obrigaria o dev a ter réplicas, backup e TLS, o que contraria a simplicidade e o §2.2 (a plataforma é o "skate"); ou, no outro extremo, deixaria cada exceção de dev sem critério nem prazo.

## Decisão

- **§2.5 Piso por ambiente.** Segurança e simplicidade valem integralmente em dev. Robustez e resiliência de **código** valem integralmente em dev, porque o código é o mesmo de prd. Robustez e resiliência de **infraestrutura** (réplicas, fila persistente, backup, retenção, quarentena, alta disponibilidade) e segurança de **infraestrutura que não existe em dev** (certificados, cofre, política de rede) podem ser menores em dev, como **lacuna declarada**. O stg tem o mesmo piso do prd.
- **Lacuna declarada** é a que registra o que falta, por que é aceitável em dev e a condição que a fecha antes do stg. O registro é o `docs/platform/IMPLEMENTATION-STATUS.md`. Uma lacuna não declarada é violação.
- **Nada é promovido a stg com lacuna aberta.** O item "Endurecimento para stg e prd" do ROADMAP é a lista dessa condição.

## Justificativa

- **Segurança:** a parte que vai a prd como código e configuração (redação de dados, menor privilégio, autorização) não relaxa em dev; só a que depende de infraestrutura inexistente em dev difere, e de forma explícita.
- **Simplicidade:** o dev não carrega alta disponibilidade, fila persistente nem cofre antes de precisar deles.
- **Robustez e resiliência:** a distinção código x infraestrutura evita relaxar o que custa o mesmo em dev e é caro de refazer depois.

## Consequências

- A tabela da seção 7.1 do `IMPLEMENTATION-STATUS.md` lista as lacunas declaradas de dev e separa o que **não** é lacuna declarável (segurança de configuração), que deve ser corrigido.
- As decisões antigas com "só em dev" (0011, 0049 e outras) passam a ser lidas como lacunas declaradas, desde que estejam na tabela.
- Risco: o dev virar um lugar permanente para as lacunas. A mitigação é a condição de saída por item e a regra de que o stg não nasce com lacuna aberta.
