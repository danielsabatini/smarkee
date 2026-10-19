# smarkee-dev-telemetry-reset

Apaga os sinais de telemetria que os telemeters de dev gravaram em disco. É uma **ferramenta de operação**, e não um componente da plataforma nem um teste.

Os telemeters (`platform-telemeter` e o de cada feature, decisões 0053 e 0062) gravam logs, métricas e traces em arquivos `*.jsonl` só para gerar dados de análise. Antes de uma nova rodada de testes, este comando zera essas pastas para a análise não misturar sinais de rodadas diferentes.

```bash
cd scripts/dev/telemetry-reset && uv sync
uv run smarkee-dev-telemetry-reset            # lista os arquivos e o tamanho; sai com 1 se houver sinal
uv run smarkee-dev-telemetry-reset --apply    # zera; sai com 1 se, depois de zerar, ainda sobrar sinal
```

## O que zera

Só `*.jsonl` (e nunca links simbólicos) nas pastas de sinais:

| Origem | Pastas |
|---|---|
| `platform-telemeter` | `infrastructure/dev/platform-telemeter/{logs/app,logs/infra,metrics/app,metrics/infra,traces}` |
| Telemeter de cada feature | `features/<módulo>/<tipo>/telemeter/{logs,traces}` |

O `.gitkeep`, a configuração dos telemeters e o resto do repositório não são tocados. Pasta de feature nova é encontrada sozinha (`features/*/*/telemeter`).

## Como zera

- **Arquivos rotacionados** (`*-size.jsonl`): são removidos.
- **Arquivo ativo** (`logs.jsonl`, `metrics.jsonl`, `traces.jsonl`): é **truncado**, e não removido. O coletor mantém esse arquivo aberto, e apagá-lo faria os próximos sinais irem para um arquivo que já não existe no disco. Os telemeters seguem rodando e gravam do zero.

## O que não zera

- A fila persistente do `telemetry-router` (`infrastructure/dev/telemetry-router/data`): é estado de execução de um banco em uso, e apagá-lo com o roteador no ar pode corrompê-lo. Sinais que ainda estejam na fila chegam aos telemeters depois do reset.
- Os logs dos contêineres no Docker (`docker logs`): vêm do driver `json-file`, com rotação própria.

## Segurança

- Sem `--apply`, nada é alterado.
- Só enxerga pastas sob a raiz do repositório, descoberta pela localização do próprio script, e recusa rodar se `infrastructure/dev/platform-telemeter` não existir.

## Desenvolvimento

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest        # roda numa árvore temporária; não toca no repositório
```
