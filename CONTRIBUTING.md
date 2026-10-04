# Contribuindo para o Smarkee

Primeiramente, obrigado pelo seu interesse em contribuir! 🎉

Este projeto adota uma abordagem moderna baseada em **Agentes de Inteligência Artificial** orquestrados em conjunto com desenvolvedores humanos. Para manter a ordem, segurança e a qualidade da base de código, estabelecemos algumas regras rígidas que devem ser seguidas por todos (humanos e IAs).

---

## 1. As Leis do Projeto (AGENTS.md)

Antes de escrever qualquer linha de código ou propor uma mudança, é **obrigatória** a leitura do arquivo [`AGENTS.md`](AGENTS.md). 
Ele é a constituição do projeto e define nossos princípios fundamentais, como:
*   Segurança e clareza antes de otimização prematura.
*   Uso do menor privilégio.
*   Separação rigorosa de responsabilidades.

## 2. Onde encontrar o que precisa

Nossa arquitetura de arquivos tem propósitos estritos baseados na regra de Fonte Única da Verdade (SSOT):

*   **`docs/`**: Documentação oficial, contratos e regras de arquitetura. Nunca duplique essas informações.
*   **`.decisions/`**: Registros de Decisões Arquiteturais (ADRs). Se você vai mudar o rumo do projeto, um ADR deve ser submetido aqui primeiro.
*   **`ROADMAP.md`**: O que estamos fazendo `Now`, o que faremos `Next` e o que fica para `Later`.
*   **`CHANGELOG.md`**: Histórico de mudanças focado em humanos (mantido sob o padrão *Keep a Changelog*).
*   **`.workspace/`**: Nossa "sandbox". Use este diretório para arquivos temporários, scripts de uso único ou experimentos. Nunca suje a raiz do projeto.
*   **`MEMORY.md`**: Área de transferência de contexto para a Inteligência Artificial. Não a utilize como documentação.

## 3. Como relatar Bugs e solicitar Features

*   **Bugs:** Seja explícito. Informe o que aconteceu, o que era esperado, e inclua logs (limpos de senhas/tokens) ou evidências de rastreamento. 
*   **Features:** Verifique o `ROADMAP.md` primeiro. Se a feature não estiver mapeada, abra uma Issue descrevendo o problema (Contexto) e a sua proposta de solução, referenciando como ela se alinha aos princípios do `AGENTS.md`.

## 4. Como enviar Código (Pull Requests)

Ao submeter um Pull Request (PR), certifique-se de que:

1.  **Pequenas Mudanças:** O PR deve aplicar o princípio da menor mudança necessária. Não inclua refatorações não relacionadas ao escopo do PR.
2.  **Verificações:** Valide o código adequadamente. Não declare sucesso sem ter evidências.
3.  **Atualização de Documentação:** Se a sua mudança altera comportamento, contratos ou operação, o diretório `docs/` correspondente **deve** ser atualizado no mesmo PR.
4.  **Atualização do Changelog:** Você deve atualizar o `CHANGELOG.md` descrevendo sua mudança sob a tag correta (`### Added`, `### Changed`, `### Fixed`, etc.).
5.  **Atualização do Roadmap:** Se você concluiu uma tarefa que estava na fase `Now` do `ROADMAP.md`, remova-a de lá.

## 5. Padrões de Versionamento

Nós utilizamos o **Semantic Versioning (SemVer)**. 
Ao preparar uma release, as versões devem seguir o formato `MAJOR.MINOR.PATCH`:
- **MAJOR:** Quebras de compatibilidade.
- **MINOR:** Novas funcionalidades retrocompatíveis.
- **PATCH:** Correções de bugs.

## 6. Configuração do Ambiente de Desenvolvimento

*Arquivos temporários*: Lembre-se, ao rodar testes ou criar artefatos secundários localmente, garanta que eles ocorram em `/tmp/opencode` ou na pasta local `.workspace/`. O `.workspace/` já está no `.gitignore` para evitar vazamentos de lixo geracional.
*Segurança*: **Nunca** comite chaves privadas, secrets ou credenciais. O `.journal/` não rastreia secrets e você também não deve.

---

Mais uma vez, bem-vindo(a) ao projeto! Seguindo essas diretrizes, você garante que nossa base permaneça sustentável, explícita e altamente resiliente.
