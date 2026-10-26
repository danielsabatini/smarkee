# 0060 — Papéis de instância da Organization mantidos (exceção deliberada)

- **Data:** 2026-10-18
- **Status:** Aceita. Resolve a pendência da decisão 0039 (seção 2) e a ressalva "estreitar antes de prd" das decisões 0038 e 0010.
- **Origem:** decisão do responsável, ao avaliar o item "papéis menores" do piso de segurança de observabilidade (decisão 0059): "vamos manter como está, se não existe no padrão".

## Contexto

O Executor da Organization usa `IAM_ORG_MANAGER` e o Observer usa `IAM_OWNER_VIEWER`, ambos de instância e mais largos que o necessário. O `IAM_ORG_MANAGER` tem 58 permissões (inclui usuários, projetos e políticas); o `IAM_OWNER_VIEWER` tem 34. O §4.2 do `AGENTS.md` pede o menor privilégio.

Em 2026-10-18 foi verificado, na documentação e no `defaults.yaml` da v4.19.4 (parte da lista de permissões por resumo, não literal), que:
- não há papel padrão menor para criar e listar organizações;
- é possível definir papéis customizados em `InternalAuthZ.RolePermissionMappings`, mas a configuração **substitui a lista inteira**, exige copiar e manter todos os papéis padrão a cada versão e só vale após `zitadel setup`;
- o `AddOrganization` v2 exige `org.write` de instância (issue 12899, aberta na v4.19.4), e a permissão do v2 para renomear, ativar, desativar e remover não foi confirmada.

## Decisão

**Manter os dois papéis de instância, em todos os ambientes.** É uma **exceção deliberada, explícita e justificada** ao menor privilégio (§4.3), e não uma lacuna de dev (§2.5): vale também em stg e prd, até o Zitadel oferecer um papel padrão menor.

- Registro: `docs/platform/IMPLEMENTATION-STATUS.md`, seção 7.1, "Exceções deliberadas", com a justificativa, os controles compensatórios e o gatilho de revisão.
- O item "papéis de instância menores" sai de "Endurecimento para stg e prd" no `ROADMAP.md`.

## Justificativa

- **Segurança:** o risco é conhecido e limitado pelos controles compensatórios: o Executor só escreve a organização; uma conta por papel, só na organização `core`; chaves em volume com modo 0400, cada componente montando só a própria.
- **Simplicidade:** substituir a lista inteira de papéis do Zitadel e mantê-la a cada versão é complexidade e risco maiores (um erro quebra papéis de toda a plataforma) do que o ganho.
- **Robustez:** o caminho customizado depende de permissões do v2 ainda não confirmadas.

## Consequências

- Os textos "estreitar antes de prd" foram alinhados (README da infra e da Organization, ROADMAP, decisão 0039).
- **Revisão** quando o Zitadel oferecer um papel padrão menor ou a customização ficar barata de manter; o gatilho está na tabela da 7.1.
- Risco aceito: uma credencial vazada de uma dessas duas contas enxerga e, no caso do Executor, escreve mais do que a Organization precisa.
