FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.7.19 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1

WORKDIR /srv

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev


# Development: adds dev dependencies; source is bind-mounted
FROM builder AS dev

RUN uv sync --locked

ENV PATH="/srv/.venv/bin:$PATH"

RUN useradd --create-home app
USER app
CMD ["flask", "--app", "app:create_app", "run", "--host", "0.0.0.0", "--port", "8000", "--debug"]


# Production (default target): only the venv and the code
FROM python:3.13-slim AS runtime

WORKDIR /srv

COPY --from=builder /srv/.venv /srv/.venv
ENV PATH="/srv/.venv/bin:$PATH"
COPY app ./app

RUN useradd --create-home app
USER app
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "app:create_app()"]
