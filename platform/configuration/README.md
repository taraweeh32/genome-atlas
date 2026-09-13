# Configuration

Three distinct configuration concerns are kept separate and are never mixed:

| Concern | Module | Contents |
| --- | --- | --- |
| A. Environment | `backend/app/core/environment.py` | environment name, connection strings, endpoints, credentials, secrets |
| B. Application | `backend/app/core/app_config.py` | platform settings, limits, policies, feature configuration |
| C. Scientific | `backend/app/core/scientific_config.py` | scientific service endpoint, adapter selection, engine/capability identity expectations |

Rules:

- Secrets come from the process environment or the deployment secret store —
  never from source, never from the frontend bundle.
- Only `NEXT_PUBLIC_*` values reach the browser; they must be non-secret.
- Every settings object is validated during application startup. A missing or
  invalid required value raises `ConfigurationError` and aborts startup rather
  than silently selecting an unsafe default.
- `SCIENTIFIC_ADAPTER=development` is rejected when `APP_ENVIRONMENT=production`.
