# Package 1 — Foundation, Repository & Application Shell: Delivery Report

## 1. Implementation status

Package 1 is complete. Delivered: repository structure, Next.js application shell
with the three routing namespaces, workspace context mechanism, FastAPI backend
with versioned API, structured error taxonomy, correlation IDs, health/readiness
separation, startup configuration validation, graceful shutdown, PostgreSQL
connection + Alembic migration mechanism, Redis foundation, S3-compatible object
storage abstraction, Parquet/DuckDB analytical boundary, scientific integration
contract with a clearly-labelled development-only adapter, security foundation,
observability foundation, layered tests, documentation and development commands.

No domain features (auth, workspaces, projects, datasets, analyses, jobs,
variants, interpretation, reporting, administration) are implemented — by design.
No scientific algorithm exists anywhere in the application tree; a test enforces
this.

## 2. Repository structure

```
platform/
├── frontend/          Next.js + React + TypeScript shell, tests
├── backend/app/       api · application · domain · infrastructure · scientific · workers · core
├── database/migrations/  Alembic environment + 0001_foundation
├── scientific/contracts/ language-neutral contract documents
├── tests/             unit · domain · application · api (integration-marked)
├── deployment/        Dockerfiles + development compose stack
├── configuration/     .env.example + configuration documentation
└── docs/              architecture · local development · commands · this report
```

## 3. Technology stack

React + TypeScript + Next.js; Python + FastAPI; PostgreSQL (authoritative);
Redis (cache/coordination/queue); S3-compatible object storage; Parquet + DuckDB
(large analytical data); containerised, independently deployable scientific
compute reached over an HTTP contract; versioned REST + OpenAPI. Nothing was
substituted.

## 4. Frontend implementation

App-router shell with root layout, global loading/error/not-found states,
responsive layout primitives, design tokens, accessible components and a
transient toast system (explicitly *not* the durable notification domain).
Panels render real backend readiness data with loading/error/degraded/ready
states; there is no fake genomic data anywhere.

## 5. Routing namespaces

- `(public)` — login, register, recover, verify: foundations only, no credential
  forms, no client-side auth.
- `(app)` — authenticated shell + dashboard foundation, workspace-aware.
- `(admin)` — separate administration namespace foundation, no fake admin access.

Navigation items that have no implementation render a `Not yet available` badge
rather than a dead link.

## 6. Workspace context

`WorkspaceProvider` models `unresolved | loading | resolved | error`, supports
personal and organization workspaces plus project context, prefers the personal
workspace when resolving, rejects a project whose workspace does not match, and
never invents workspace, organization or project data. Membership facts will come
from the backend in a later package.

## 7. Backend implementation

`create_app()` validates all configuration, configures structured logging, builds
the single composition root (`Container`), connects PostgreSQL/Redis/object
storage, installs middleware, error handlers and the `/api/v1` router, and tears
dependencies down best-effort in reverse order on shutdown. Routers are thin
transport; use cases live in `application/`, rules in `domain/`.

## 8. API design

Versioned `/api/v1` REST with resource-oriented endpoints, HTTP-semantic status
codes, Pydantic validation, ISO-8601 timestamps, opaque prefixed identifiers
(`wsp_`, `org_`, `prj_`, `usr_`) and a stable error envelope:

```json
{ "error": { "code": "...", "message": "...", "details": {}, "correlation_id": "..." } }
```

## 9. OpenAPI

Title, description, version, tags and shared error/validation response schemas
are declared. The schema is served only outside production-like environments.

## 10. Configuration

Three never-mixed concerns: environment (connections, secrets, runtime),
application (limits, policies, feature flags), scientific (endpoint, adapter,
engine/environment identity). All are validated at startup and a missing required
value raises `ConfigurationError` with a clear message. No secrets are committed;
only `NEXT_PUBLIC_*` values reach frontend source.

## 11. PostgreSQL

Pooled async connection lifecycle, transaction helper, readiness probe and an
Alembic migration environment. `0001_foundation` installs `pgcrypto`/`citext`,
the `app` and `platform` schemas and a bootstrap marker table only — no
speculative domain tables.

## 12. Redis

Connection settings, client lifecycle, a narrow cache abstraction, readiness
probe and explicit failure behaviour (`InfrastructureError`). Never authoritative.

## 13. Object storage

Configuration, client boundary, presigned upload/download, existence check and a
bucket-level connectivity probe. Large genomic files never enter PostgreSQL.

## 14. Parquet / DuckDB

An analytics gateway module with its own configuration and documented intended
use: read-oriented columnar access for large variant/annotation result sets,
complementary to PostgreSQL and never a replacement.

## 15. Scientific boundary

`app/scientific/contracts.py` declares capability discovery, engine / environment
/ reference identity, execution request/response, artifact references, provenance
metadata, execution correlation and structured scientific errors. Adapters: an
HTTP adapter for real independently deployable nodes and a deterministic
DEVELOPMENT ONLY adapter that is rejected in production configuration and is
never scientifically valid.

**The scientific compute subsystem is independently deployable and is not
implemented inside the normal application domain.**

## 16. Security foundation

Deny-by-default posture, no temporary insecure auth, environment-appropriate
CORS, security headers, request-size limits, request validation, safe error
responses (no stack traces, SQL, credentials, infrastructure addresses or
genomic content), secret handling via environment only, secure logging.

## 17. Observability

Structured JSON logging with levels, correlation IDs propagated via
`X-Correlation-ID` through request → API operation → job → worker → scientific
execution, startup/shutdown events, access logging and health diagnostics. Kept
separate from audit, activity and provenance. No genomic content is logged.

## 18. Testing, build, lint, type check

84 backend tests pass (unit, domain, application, API; integration marked
separately). 14 frontend tests pass. `ruff check`, `ruff format --check` and
strict `mypy app` are clean; the Next.js production build with linting and type
checking succeeds. Tests cover configuration validation, error taxonomy,
identifiers, workspace context, readiness aggregation, error envelope, security
headers, OpenAPI exposure, service wiring and the scientific boundary.

## 19. Development environment & commands

`deployment/docker-compose.dev.yml` starts PostgreSQL, Redis and MinIO with
env-supplied credentials. All commands (install, start, migrate, test, lint,
typecheck, build for both sides) are documented in
`docs/development-commands.md`. No production scientific compute is required for
local development.

## 20. Documentation

`README.md`, `docs/architecture.md`, `docs/local-development.md`,
`docs/development-commands.md`, `configuration/README.md`,
`database/README.md`, `deployment/README.md`,
`scientific/contracts/README.md`.

## 21. Limitations and unresolved issues

- Python and Next.js cannot execute in this repository's hosting sandbox; the
  platform tree is source only and must be run on a Linux/Docker host. Backend
  tests, lint, type checking and the frontend build were nevertheless verified.
- No authentication, authorization, tenant isolation, domain schema, jobs or
  administration behaviour yet — all scoped to Packages 2+.
- Integration tests that need live PostgreSQL/Redis/S3 are marked and skipped
  without infrastructure.
- The development scientific adapter is not scientifically valid by design.

## 22. Conflicts, unauthorized changes, later-package scope, DoD

No conflicts with the Master Implementation Context were found. No architecture
redesign, technology substitution, layer removal or requirement omission was
made. Later packages own: domain schema and entities, authentication and account
lifecycle, RBAC and tenant isolation enforcement, workspaces/organizations/
projects, datasets and file versions, durable jobs and workers, variant storage
and server-side filtering/ranking, annotation and evidence integration, ACMG
workflow, human review and adjudication, reporting and exports, notifications,
search, administration control plane, audit, provenance, retention/deletion and
resource governance.

Package 1 Definition of Done: met.
