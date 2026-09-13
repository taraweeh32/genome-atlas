"""OpenAPI metadata for the versioned REST contract."""

from __future__ import annotations

from app.core.app_config import API_VERSION

API_TITLE = "Genomic Analysis & Variant Interpretation Platform API"

API_DESCRIPTION = """
Versioned REST API for the Genomic Analysis & Variant Interpretation Platform.

Conventions
-----------
* Resource-oriented paths under `/api/v1`.
* `GET` reads, `POST` creates/commands, `PATCH` partial updates, `DELETE` removes.
* All timestamps are ISO-8601 UTC.
* Identifiers are opaque prefixed strings; database keys are never exposed.
* Every response echoes `X-Correlation-ID`.
* Errors use `{ "error": { "code", "message", "details?", "correlation_id" } }`
  with the codes `validation_error`, `authentication_error`,
  `authorization_error`, `not_found`, `conflict`, `invalid_state_transition`,
  `dependency_failure`, `infrastructure_failure`,
  `scientific_integration_failure`, `internal_error`.

Scientific boundary
-------------------
All genomic computation is performed by an independently deployable scientific
compute subsystem. This API exposes only its declared identity, capabilities and
execution outcomes.
""".strip()

OPENAPI_TAGS = [
    {"name": "system", "description": "Liveness, readiness and API metadata."},
    {"name": "scientific", "description": "Scientific subsystem identity and capabilities."},
]

API_CONTRACT_VERSION = API_VERSION
