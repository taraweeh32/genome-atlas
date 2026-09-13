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
