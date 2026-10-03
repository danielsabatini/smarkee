---
name: Python Quality
description: Executar a validação completa de qualidade de um componente Python, incluindo lint, formatação, type checking, testes, coverage e Quality Gate do SonarQube.
---

# Python Quality

## Objetivo

Executar o workflow completo de validação de qualidade de um componente Python.

Esta skill define **o procedimento de execução**.

As regras e configurações das ferramentas pertencem aos respectivos agents:

- Python → `python.md`
- SonarQube → `sonarqube.md`
- Regras gerais → `AGENTS.md`

Não redefina aqui as regras dessas ferramentas.

---

# Workflow

## 1. Identificar o componente

Determine qual componente Python deve ser analisado.

O componente pode ser qualquer projeto ou componente Python que siga as convenções definidas em `python.md`.

Execute a validação a partir do diretório do projeto Python correspondente ou utilizando o workspace configurado pelo projeto.

---

## 2. Sincronizar o ambiente

Garanta que as dependências estejam sincronizadas utilizando o mecanismo definido pelo projeto.

Para projetos gerenciados por uv:

```text
uv sync
```

Não altere dependências apenas para executar a análise.

---

## 3. Executar Ruff

Execute o lint e a validação de formatação definidos pelo padrão Python do projeto.

```text
uv run ruff check .
uv run ruff format --check .
```

Se houver problemas de formatação, não considere a validação concluída.

---

## 4. Executar Pyright

Execute o type checking:

```text
uv run pyright
```

Falhas de tipagem devem ser tratadas antes de considerar o componente validado.

---

## 5. Executar pytest e coverage

Execute os testes com coverage:

```text
uv run pytest --cov --cov-report=term-missing
```

Confirme:

- execução dos testes;
- resultado dos testes;
- resultado do coverage.

Uma análise de qualidade não deve ser considerada concluída quando os testes falharem.

---

## 6. Executar análise do SonarQube

Execute a análise do componente utilizando o mecanismo de análise configurado para o projeto.

A configuração do scanner, project key, URL e autenticação deve ser obtida das configurações existentes.

Não invente valores de configuração.

---

## 7. Aguardar processamento

O término do scanner não significa que o Quality Gate esteja disponível.

Aguarde o processamento da análise pelo SonarQube antes de consultar o resultado.

Quando existir um identificador da tarefa de processamento, utilize-o para acompanhar a análise.

---

## 8. Consultar Quality Gate via API

Consulte obrigatoriamente o Quality Gate através da Web API do SonarQube.

Endpoint:

```text
/api/qualitygates/project_status
```

Utilize o project key e, quando aplicável, branch, pull request ou identificador da análise correspondente à execução atual.

Não utilize somente a interface web para determinar o resultado.

---

## 9. Validar o resultado

Registre separadamente:

```text
Ruff
Pyright
pytest
Coverage
SonarQube Analysis
Quality Gate
```

O resultado do Quality Gate deve corresponder à análise executada.

Não reutilize o resultado de uma análise anterior.

---

## 10. Falha de Quality Gate

Quando o Quality Gate falhar:

1. Identifique as condições responsáveis.
2. Identifique os problemas relacionados quando disponíveis.
3. Corrija os problemas pertencentes ao escopo.
4. Execute novamente a análise.
5. Aguarde o processamento.
6. Consulte novamente o Quality Gate via API.

Não considere o problema resolvido sem nova validação.

---

# Resultado

Ao concluir, apresente o resultado de forma explícita:

```text
Python Quality

Ruff: PASS/FAIL
Pyright: PASS/FAIL
pytest: PASS/FAIL
Coverage: PASS/FAIL
SonarQube Analysis: PASS/FAIL
Quality Gate: PASS/FAIL

Overall: PASS/FAIL
```

Quando alguma etapa não puder ser executada, informe:

```text
NOT VERIFIED
```

e explique a razão.

Não transforme uma etapa não executada em sucesso.

---

# Regra da Skill

Esta skill define somente **como executar o workflow de validação**.

Não copie para esta skill:

- regras gerais do `AGENTS.md`;
- convenções Python do `python.md`;
- configuração das ferramentas Python;
- política do SonarQube;
- definição do Quality Gate.

Esses temas possuem suas próprias fontes da verdade.