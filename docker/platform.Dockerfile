# The platform image: `metamorph` CLI (migrations now; loader, resolver and publish in later phases).
FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.27 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY packages ./packages
COPY src ./src
RUN uv sync --frozen --no-dev

USER nobody
ENTRYPOINT ["metamorph"]
