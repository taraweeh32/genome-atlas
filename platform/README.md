# Genomic Analysis & Variant Interpretation Platform

Package 1 — Foundation, Repository & Application Shell.

> **Runtime notice.** This directory contains the platform source tree for the
> locked technology stack (Next.js frontend, Python/FastAPI backend, PostgreSQL,
> Redis, S3-compatible object storage, Parquet/DuckDB). This repository's hosting
> sandbox cannot execute Python or Next.js, so these files are provided as source
> only. They are intended to be run on a normal Linux/Docker development host.

## 1. Project purpose

A multi-tenant platform for genomic analysis and variant interpretation. The
application layer manages workspaces, projects, datasets, files, analyses, jobs,
variant review, evidence, interpretation, reporting, audit and provenance. All
scientific computation is performed by an **independently deployable scientific
compute subsystem** reached through an explicit contract/adapter.

## 2. Repository structure

```
platform/
├── frontend/                 Next.js + React + TypeScript application shell
│   ├── src/app/(public)/     login / register / recover / verify
│   ├── src/app/(app)/        authenticated application shell + dashboard
│   ├── src/app/(admin)/      administration namespace foundation
│   ├── src/components/       reusable component + shell foundation
│   ├── src/context/          workspace context foundation
│   ├── src/lib/              API client, config, types
│   └── tests/                frontend unit tests
├── backend/
│   └── app/
│       ├── api/              transport: FastAPI routers, schemas, error mapping
│       ├── application/      use cases, ports, application context
│       ├── domain/           entities, value objects, domain errors
│       ├── infrastructure/   postgres, redis, object storage, duckdb, logging
│       ├── scientific/       scientific integration contract + adapters
│       └── workers/          background/job worker entry point
├── database/migrations/      Alembic migration environment + versions
├── scientific/contracts/     Language-neutral scientific contract documents
├── tests/                    unit / domain / application / api / integration
├── deployment/               Dockerfiles + development compose stack
├── configuration/            .env.example and configuration documentation
└── docs/                     architecture and developer documentation
```

## 3. Architecture overview

```
Frontend  →  API / Transport  →  Application / Use cases  →  Domain
                                          ↓
                             Infrastructure  →  Persistence / External services

Application  →  Scientific integration contract / adapter
                              ↓
             Independent scientific compute subsystem (separate deployment)
```

See [docs/architecture.md](docs/architecture.md) for the full description.

## 4. Frontend / backend separation

The frontend renders and orchestrates UI only. It is **not authoritative** for
security or domain state: every authorization decision, workspace membership fact
and domain invariant is owned by the backend. The frontend talks to the backend
exclusively through the versioned REST API (`/api/v1`).

## 5. Domain / application / infrastructure separation

- `domain/` — entities, value objects, domain errors, invariants. No framework or
  I/O imports.
- `application/` — use cases and ports (protocols). Orchestrates domain objects
  and infrastructure through interfaces; owns transaction boundaries.
- `infrastructure/` — concrete adapters for PostgreSQL, Redis, object storage,
  DuckDB, logging.
- `api/` — thin FastAPI transport: validation, serialization, error mapping.

## 6. PostgreSQL role

Authoritative transactional database for all application/domain state.

## 7. Redis role

Cache, ephemeral state, distributed coordination and job/queue infrastructure.
Never authoritative for transactional data.

## 8. Object storage role

S3-compatible storage for uploaded genomic files, derived artifacts, exports and
reports. Large files never live in PostgreSQL.

## 9. Parquet / DuckDB role

Columnar analytical layer for large genomic result sets (variant tables,
annotations, per-analysis result matrices). Read-oriented and complementary to
PostgreSQL — never a replacement for the authoritative transactional store.

## 10. Scientific subsystem boundary

**The scientific compute subsystem is independently deployable and is not
implemented inside the normal application domain.** The application only knows
the contract in `backend/app/scientific/contracts.py`: capability discovery,
engine/environment/reference identity, execution request/response, structured
scientific errors, artifact references and provenance metadata.

## 11–15. Local development, configuration, database, testing, commands

See [docs/local-development.md](docs/local-development.md) and
[docs/development-commands.md](docs/development-commands.md).
