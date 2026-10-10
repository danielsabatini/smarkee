# Imagem do serviço `core` (decisão 0011). Fase de build separada da de execução: a imagem final
# não leva o uv, os testes nem as dependências de desenvolvimento, e roda sem privilégios.
FROM ghcr.io/astral-sh/uv:0.11.19-python3.14-trixie-slim AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim-trixie
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin core
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001
EXPOSE 8000
CMD ["core"]
