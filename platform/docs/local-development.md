# Local Development Setup

## Prerequisites

- Linux/macOS host with Docker + Docker Compose
- Python 3.12+ and [uv](https://docs.astral.sh/uv/) (or `pip` + venv)
- Node.js 20+ and npm

## 1. Configuration

```sh
cp configuration/.env.example .env
```

Edit `.env`. No secret has a usable default: startup fails loudly when a
required value is missing. Never commit `.env`.

## 2. Infrastructure dependencies

```sh
docker compose -f deployment/docker-compose.dev.yml up -d
```

This starts PostgreSQL, Redis and MinIO (S3-compatible object storage). The
scientific compute subsystem is **not** required to start the application shell;
set `SCIENTIFIC_ADAPTER=development` locally.

## 3. Backend

```sh
cd backend
uv sync                      # or: pip install -e '.[dev]'
uv run alembic upgrade head   # apply migrations
uv run uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/api/v1/docs

## 4. Frontend

```sh
cd frontend
npm install
npm run dev
```

Application: http://localhost:3000

## 5. Database

Migrations live in `database/migrations/versions`. Create a new one with
`uv run alembic revision -m "description"`. Package 1 contains only the
foundation migration (schema bootstrap + migration bookkeeping); the domain
schema arrives in Package 2.

## 6. Testing

```sh
cd backend && uv run pytest              # unit, domain, application, api
cd backend && uv run pytest -m integration   # requires the compose stack
cd frontend && npm test
```

## 7. Environments

`APP_ENVIRONMENT` is one of `development`, `test`, `staging`, `production`.
CORS, error verbosity and the availability of the development scientific adapter
are all environment-derived.
