# Imagem única de sum.service (decisão 0063): contém o código de todos os papéis da feature. Cada
# papel roda como contêiner próprio, escolhido pelo `command` (por exemplo, `sum-service-publisher`);
# sem `command`, a imagem não inicia nenhum papel.
# As credenciais não ficam na imagem: cada contêiner recebe só as do seu papel.
#
# Segue o guia do uv para Docker (https://docs.astral.sh/uv/guides/integration/docker/):
# - as imagens são fixadas por tag e por digest (a tag sozinha pode ser movida). Para atualizar, troque
#   a tag e o digest juntos: `docker buildx imagetools inspect <imagem>:<tag>`;
# - os dois estágios usam a mesma base (Debian trixie, Python 3.14), e o uv só é copiado para o estágio
#   de build: a imagem final não leva o uv, o cache, os testes nem as dependências de desenvolvimento;
# - as dependências ficam numa camada própria, que só muda com `pyproject.toml` ou `uv.lock`.

FROM python:3.14-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.19@sha256:b46b03ddfcfbf8f547af7e9eaefdf8a39c8cebcba7c98858d3162bd28cf536f6 /uv /uvx /bin/
WORKDIR /app
# UV_PYTHON_DOWNLOADS=0: usa só o Python desta imagem (o mesmo do runtime) e falha, em vez de baixar outro.
# UV_NO_DEV=1: sem dependências de desenvolvimento.
ENV UV_PYTHON_DOWNLOADS=0 UV_NO_DEV=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Camada das dependências. `--locked` falha se o `uv.lock` não corresponde ao `pyproject.toml`.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-editable

# Camada do projeto: muda a cada alteração de código.
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

FROM python:3.14-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin sum
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001
EXPOSE 8000
