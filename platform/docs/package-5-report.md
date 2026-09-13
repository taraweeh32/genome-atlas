# Package 5 implementation report — Analysis definitions, configurations, executions, jobs & scheduling

## 1. Scope delivered

Application-side orchestration for defining analyses, versioning their
configurations, requesting executions, executing them as durable jobs on
capability-aware compute nodes, scheduling recurring runs, recording provenance,
and monitoring/administering all of it. No scientific algorithm was implemented.

## 2. What was explicitly not implemented

VEP, normalization, liftover, HGVS generation, consequence calculation,
population-frequency computation, annotation, clinical evidence interpretation,
ACMG criteria evaluation or classification, variant filtering logic, variant
ranking algorithms, scientific inference. Filtering/ranking *configuration* is
carried and versioned; the computation belongs to the scientific subsystem.

## 3. Architectural position

Frontend → REST → use cases → domain → persistence → jobs/workers → scientific
adapter → independent engine. Package 5 added layers only inside that chain; no
technology was substituted and no earlier package was redesigned.

## 4. Domain model

`app/domain/analysis/`: `entities.py` (immutable analysis, configuration,
execution, job, schedule, compute-node entities with named transition methods),
`policies.py` (`ResourceRequirements`, `node_class_for`, `LeasePolicy`,
`clamp_priority`), `scheduling.py` (node selection), `schedule.py` (expression
grammar, next-firing resolution, missed-firing policy with a 300-second
punctuality grace).

## 5. Lifecycle and state machines

All transitions go through `require_transition` in `app/domain/lifecycle.py`.
Analysis: draft → ready/active → archived. Execution: queued → submitted →
running → succeeded/failed/cancelled, with `cancel_requested` distinct from
`cancelled`. Job: pending/queued → claimed → running → terminal, plus
`retry_waiting`, `stale`, `cancelling`, `dead_letter`. Invalid transitions are
refused server-side.

## 6. Configurations and immutability

Versioned per analysis with a unique `(analysis_id, version_number)`, one column
per scientific concern, registry references, declared inputs with roles, content
hash and validation state. Existing versions are never mutated; activation only
selects the version a future execution uses.

## 7. Executions and snapshots

An execution freezes the configuration snapshot, records its input dataset
versions, its correlation ID and its attempt sequence. Append-only: a re-run
creates a new row and never rewrites history.

## 8. Durable jobs

`platform.jobs` plus `platform.job_attempts`. Enqueue happens in the same
transaction as the business change, so a rolled-back request leaves no orphan job
and a committed request never loses its job.

## 9. Claiming and concurrency

Atomic claim with `SKIP LOCKED`, filtered by queue, node class and handler kinds,
ordered by priority then availability. Two workers cannot claim the same job.

## 10. Leases, heartbeats and stale recovery

Each claim takes a lease; the worker heartbeats. `RecoverAbandonedWork` marks
jobs whose lease expired as stale and requeues them within the attempt budget.

## 11. Retries

Only failures classified transient retry, with bounded backoff and a max-attempt
cap; exhaustion dead-letters the job with the recorded failure code, message and
error class.

## 12. Cancellation

Cancellation is a request recorded with time and requester. The worker
acknowledges cooperatively; the UI shows `cancel_requested` until the server
reports work actually stopped.

## 13. Idempotency

Enqueue is idempotent on `idempotency_key`; a retried request reuses the existing
job instead of duplicating work.

## 14. Priorities and queues

Priority is clamped 1–1000 (default 100) and queues are constrained values.
Both are recorded on execution and job.

## 15. Resource requirements and node class

Requirements (CPU cores, memory MiB, disk MiB) derive from the configuration's
execution profile; `node_class_for` maps them to a node class used for both
claiming and node selection.

## 16. Scheduling

Explicit validated grammar (`every:<n>[m|h|d]` with a 5-minute floor,
`daily:HH:MM`, `weekly:<dow>:HH:MM`, `monthly:<1-28>:HH:MM`) evaluated in the
schedule's IANA timezone (`tzdata` added as a dependency). Concurrency and
missed-firing policies plus a catch-up limit bound backlog replay.

## 17. Scheduled analyses

`TriggerDueSchedules` resolves due firings, applies policies, requests executions
and advances `next_execution_at`. The trigger itself performs no work.

## 18. Compute nodes

Registered nodes carry class, queues, declared capabilities, capacity, lifecycle
and health state. `select_node` filters by class, queue, capability and resource
fit, requires schedulability, then picks least-loaded.

## 19. Scientific boundary

The worker submits a `ScientificExecutionRequest` through the existing gateway
contract and records the structured response, artifact references and provenance.
No scientific logic exists in routes, use cases, ORM models, handlers or React.

## 20. Development adapter

`DevelopmentScientificAdapter` is deterministic, selected only by explicit
configuration, reports `is_development_adapter: true`, and is never presented as
production scientific computation.

## 21. Provenance

Per execution: input dataset versions, configuration snapshot, capability and
version, engine version, environment version, container image digest, node
identity, reference resource identities, timestamps, parameter digest, artifact
references, correlation ID. Unrecorded facts are reported as unrecorded.

## 22. Authorization

Deny-by-default. New permissions: workspace `WORKSPACE_ANALYSIS_*`,
`WORKSPACE_SCHEDULE_MANAGE`, `WORKSPACE_JOB_READ`; project `PROJECT_ANALYSIS_*`,
`PROJECT_JOB_READ`, `PROJECT_SCHEDULE_MANAGE`; platform `PLATFORM_JOB_READ`,
`PLATFORM_JOB_ADMINISTER`, `PLATFORM_COMPUTE_READ`, `PLATFORM_COMPUTE_ADMINISTER`,
`PLATFORM_SCHEDULE_ADMINISTER`. Archived projects grant read-only capabilities
plus reopen.

## 23. Tenant isolation

Scope is always read from the stored resource row, never from the request. A
cross-tenant identifier yields a refusal indistinguishable from absence.

## 24. Persistence

Migration `0005` adds analysis/execution/job/schedule/compute-node structures,
state check constraints, uniqueness and the indexes the claim and monitoring
queries need. Domain state in `app`, operational bookkeeping in `platform`.

## 25. API surface

`/analyses`, `/analyses/{id}` (+ `/state`, `/deletion`, `/configurations`,
`/configurations/{id}/activation`, `/executions`), `/analysis-executions`
(+ `/{id}/provenance`, `/{id}/cancellation`), `/jobs`, `/analysis-schedules`
(+ `/{id}/state`, `/{id}/triggers`), `/administration/jobs`,
`/administration/compute-nodes`. All versioned under `/api/v1` with OpenAPI.

## 26. Administrative control

Platform-scoped job listing, inspection, cancellation and requeue plus compute
node registration and lifecycle control, each gated by platform permissions and
refused for organization administrators.

## 27. Worker runtime

`app/workers/runtime.py` (`JobRuntime`, `WorkerIdentity`), `dispatch.py` and the
worker entry point wired through the container: claim, lease, heartbeat, dispatch,
retry, recovery and schedule triggering on bounded intervals with graceful
shutdown.

## 28. Frontend

`/analyses` list and definition creation, `/analyses/{id}` with configuration
versions, executions and provenance, `/jobs` with state filtering and attempt
history. Nav entries for analyses and jobs enabled. All rendering follows server
capability answers; explicit loading, empty, error and refusal states throughout.

## 29. Observability

Correlation IDs propagate request → use case → job → attempt → scientific
execution → artifact. Structured logs carry identifiers, never genomic content.

## 30. Data semantics preserved

Unknown, zero, false and not-applicable stay distinct: unreported progress is not
0%, an expired lease is not a failure, a cancellation request is not a
cancellation, a retry backoff is not queue latency.

## 31. Tests

Backend suite: 272 passed, 2 deprecation warnings
(`cd platform/backend && uv run python -m pytest -q`). New coverage: definitions
and configurations, executions and jobs, schedules and recovery, and HTTP-level
analysis endpoint tests (anonymous refusal, CSRF, queue-only execution, tenant
isolation, administrative closure, scoped job listing).
Frontend: 33 tests passed across 6 files, typecheck clean, lint clean.

## 32. Verification performed

Backend `pytest`, frontend `tsc --noEmit`, `vitest run` and `next lint` all run
and read in full; all green.

## 33. Compatibility with Packages 1–4

Foundation, persistence model, identity/authorization and dataset ingest were
extended, not redesigned. Dataset versions remain immutable and are consumed
read-only as execution inputs.

## 34. Known deferred items

- Package 2 migration hardening (carried from Package 2).
- Duplicate `TokenHasher` / `SystemClock` instances in the container.
- Inherited ruff lint debt in `tests/api/*.py` (I001, RUF100), left untouched for
  consistency with existing files.
- Mail transport still a development sink.

## 35. Conflicts found

None. No requirement had to be reduced, and no locked technology was replaced.
