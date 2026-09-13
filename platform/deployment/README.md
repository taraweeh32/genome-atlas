# Deployment

Four environments, identical images, environment-injected configuration:
`development`, `test/ci`, `staging`, `production`.

| Artifact | File |
| --- | --- |
| Backend API + worker image | `Dockerfile.backend` (build context: `platform/`) |
| Frontend image | `Dockerfile.frontend` (build context: `platform/`) |
| Local infrastructure | `docker-compose.dev.yml` |

Rules:

- No secret is ever baked into an image. Every credential is injected at runtime
  from the environment or the deployment secret store.
- Only non-secret `NEXT_PUBLIC_*` values may exist at frontend build time.
- Containers run as a non-root user.
- Orchestration must probe `GET /api/v1/ready` for traffic admission and
  `GET /api/v1/health` for liveness restarts.
- The worker runs from the same backend image via
  `python -m app.workers.worker`.
- The scientific compute subsystem is deployed and versioned **independently**;
  it is not part of these images and is not required for the application to
  start.
