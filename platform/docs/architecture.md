# Architecture Overview

## Layers

| Layer | Location | Responsibility | May depend on |
| --- | --- | --- | --- |
| Frontend | `frontend/` | Presentation, navigation, workspace UI context | Versioned REST API only |
| API / transport | `backend/app/api` | Routing, request validation, serialization, error mapping, correlation IDs | application, api schemas |
| Application | `backend/app/application` | Use cases, orchestration, transaction boundaries, authorization-context propagation | domain, ports |
| Domain | `backend/app/domain` | Entities, value objects, domain services, domain errors, invariants | nothing |
| Infrastructure | `backend/app/infrastructure` | PostgreSQL, Redis, object storage, DuckDB, logging | domain/application ports |
| Scientific integration | `backend/app/scientific` | Contract + adapters to the independent scientific subsystem | domain types only |

Dependency rule: dependencies point inward. `domain` imports nothing from
`api`, `infrastructure` or `scientific`. Infrastructure implements ports
declared by `application`.

## Request lifecycle

1. ASGI middleware assigns/propagates a correlation ID (`X-Correlation-ID`).
2. Security headers and CORS policy are applied per environment.
3. Request body/query validated by Pydantic schemas in `api/v1/schemas`.
4. Route handler resolves dependencies and calls exactly one use case.
5. Use case orchestrates domain objects and ports; commits the unit of work.
6. Domain/application errors are translated to the stable API error envelope.
7. Structured JSON access log emitted with correlation ID, status and duration.

## Error taxonomy

`backend/app/domain/errors.py` defines the taxonomy; `backend/app/api/errors.py`
maps it to HTTP status codes and the stable error envelope.

| Domain error | HTTP | `error.code` |
| --- | --- | --- |
| `ValidationError` | 422 | `validation_error` |
| `AuthenticationError` | 401 | `authentication_error` |
| `AuthorizationError` | 403 | `authorization_error` |
| `NotFoundError` | 404 | `not_found` |
| `ConflictError` | 409 | `conflict` |
| `InvalidStateTransitionError` | 409 | `invalid_state_transition` |
| `DependencyFailureError` | 502 | `dependency_failure` |
| `InfrastructureError` | 503 | `infrastructure_failure` |
| `ScientificIntegrationError` | 502 | `scientific_integration_failure` |
| anything else | 500 | `internal_error` |

Outside development, responses never contain stack traces, SQL text, secrets,
infrastructure hostnames or genomic content.

## Health vs readiness

- `GET /api/v1/health` — liveness. The process is up and can serve HTTP.
- `GET /api/v1/ready` — readiness. Aggregates dependency probes (PostgreSQL,
  Redis, object storage, scientific integration when configured). Returns `503`
  when any *required* dependency is unavailable, so orchestrators do not route
  traffic to an unready instance.

## Observability vs audit vs provenance

Three separate concerns, deliberately not merged:

- **Operational observability** (this package): structured logs, levels,
  correlation IDs, startup/shutdown events, health diagnostics.
- **Audit / activity** (later package): durable, user-visible record of actions.
- **Scientific provenance** (later package): engine, environment and reference
  resource identity attached to results.

Correlation propagates request → API operation → job → worker → scientific
execution → artifact via the `correlation_id` field carried in the scientific
execution request and job payloads.

## Configuration architecture

Three separated configuration concerns, each its own settings object:

- `core/environment.py` — `EnvironmentSettings`: environment name, database URL,
  Redis URL, object-storage endpoint/credentials, service URLs, secrets.
- `core/app_config.py` — `ApplicationSettings`: platform limits, policies,
  feature configuration.
- `core/scientific_config.py` — `ScientificSettings`: scientific service
  endpoint, adapter selection, capability/engine identity expectations.

All are validated at startup. Missing required configuration raises
`ConfigurationError` and aborts startup; production never falls back to
development defaults.

## Scientific integration boundary

The application never performs scientific computation. It:

1. discovers capabilities and engine/environment/reference identity,
2. submits a `ScientificExecutionRequest` carrying a correlation ID,
3. receives a `ScientificExecutionResponse` with artifact references and
   provenance metadata, or a structured `ScientificIntegrationError`.

Adapters:

- `adapters/http.py` — real adapter for an independently deployed scientific node.
- `adapters/development.py` — **DEVELOPMENT ONLY**, deterministic, refuses to
  initialize when `APP_ENVIRONMENT=production`. Not scientifically valid.

No VEP, normalization, annotation, ACMG, evidence, pipeline, clinical-resource or
population-frequency logic exists in the application tree.
