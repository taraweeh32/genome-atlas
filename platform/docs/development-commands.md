# Development Commands

## Infrastructure

| Task | Command |
| --- | --- |
| Start PostgreSQL/Redis/MinIO | `docker compose -f deployment/docker-compose.dev.yml up -d` |
| Stop | `docker compose -f deployment/docker-compose.dev.yml down` |
| Reset volumes | `docker compose -f deployment/docker-compose.dev.yml down -v` |

## Backend (`cd backend`)

| Task | Command |
| --- | --- |
| Install dependencies | `uv sync` |
| Start API | `uv run uvicorn app.main:app --reload --port 8000` |
| Start worker | `uv run python -m app.workers.worker` |
| Run migrations | `uv run alembic upgrade head` |
| New migration | `uv run alembic revision -m "message"` |
| Tests | `uv run pytest` |
| Integration tests | `uv run pytest -m integration` |
| Lint | `uv run ruff check .` |
| Format check | `uv run ruff format --check .` |
| Type check | `uv run mypy app` |
| Build image | `docker build -f ../deployment/Dockerfile.backend -t genomics-api ..` |

## Frontend (`cd frontend`)

| Task | Command |
| --- | --- |
| Install dependencies | `npm install` |
| Dev server | `npm run dev` |
| Tests | `npm test` |
| Lint | `npm run lint` |
| Type check | `npm run typecheck` |
| Production build | `npm run build` |

## Identity and tenancy (Package 3)

| Task | Command |
| --- | --- |
| Apply the identity/session migration | `uv run alembic upgrade head` |
| Identity, session and authorization tests | `uv run pytest ../tests/identity ../tests/tenancy` |
| Grant the first platform administrator | `uv run python -m app.workers.worker --help` is *not* used for this; use `POST /admin/users/{id}/platform-roles` from an existing platform administrator, or insert the role row directly in a fresh environment |

`AUTH_TOKEN_PEPPER` must be set for every environment (see
`configuration/.env.example`). In development, verification, password-reset and
invitation tokens are returned in API responses because no mail transport is
configured; this never happens in any other environment.
