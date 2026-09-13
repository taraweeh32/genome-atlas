# Analyses, executions, jobs and scheduling

Package 5 adds the application-side orchestration for running analyses. It adds
**no scientific algorithm**: every scientific step happens inside the
independently deployed compute subsystem, reached only through the contract in
`app/scientific/contracts.py`.

## The lifecycle

```text
Analysis definition            reusable, named, one project
  → Analysis configuration     versioned, immutable, declares inputs + parameters
    → Analysis execution       one requested run, append-only
      → Execution snapshot     configuration frozen at request time
        → Job                  durable work in platform.jobs
          → Queue + node class capability/resource aware placement
            → Worker           claims with a lease, heartbeats, retries
              → Scientific execution request  (contract call)
                → Scientific engine           (independent subsystem)
                  → Scientific execution result + artifact references
                    → Execution completion + provenance
```

Scheduled analyses enter at the execution step: a schedule resolves due firings,
applies its concurrency and missed-firing policies, and requests executions.
The schedule never runs work itself.

## Separations that must not collapse

| Concept | Why it is separate |
| --- | --- |
| Definition vs configuration | A definition is reusable; parameters change over time and each change is a new version. |
| Configuration vs execution | A later configuration edit must never rewrite what a past run used. |
| Execution vs job | The execution is domain history; the job is operational bookkeeping (`platform` schema). |
| Job vs scientific execution | The application worker orchestrates; the scientific node computes. Distinct records, distinct versions. |
| `cancel_requested` vs `cancelled` | A request to stop is not evidence work stopped. |
| `retry_waiting` vs `queued` | A backoff must be visible, not disguised as queue latency. |
| `stale` vs `failed` | A lease expiring means the worker is presumed gone, not that the work is known bad. |
| Progress not reported vs 0% | Unknown and zero are never conflated. |

## Configurations

A configuration version keeps each scientific concern in its own column
(filtering, ranking, annotation, evidence, interpretation, reporting, execution
parameters) plus registry references (pipeline, engine, reference genome,
ruleset, execution profile) and declared inputs with roles. Content is defined
by the scientific contract, not by the application. Versions are immutable;
activation only changes which version a *new* execution uses.

An analysis is executable only when the server says so (`is_executable`): an
active configuration version whose declared inputs are accepted, immutable
dataset versions.

## Executions and provenance

Requesting an execution:

1. authorizes against the scope recorded on the analysis,
2. freezes the configuration into the execution snapshot,
3. records the declared input dataset versions,
4. enqueues a durable job in the same transaction.

Provenance recorded per run: input dataset versions, configuration snapshot,
capability and version, engine version, environment version, container image
digest, node identity, reference resource identities, timestamps, parameter
digest, produced artifact references, correlation ID. A fact that was not
recorded is reported as unrecorded — never substituted.

## Jobs and workers

Durable jobs live in `platform.jobs` with attempt history in
`platform.job_attempts`. The worker:

- claims atomically (`SKIP LOCKED`) filtered by queue, node class and kind,
- holds a lease and heartbeats; an expired lease makes the job `stale`,
- recovers abandoned work on a bounded schedule,
- retries only transient failures, with backoff and a max-attempt cap, then
  dead-letters,
- honours cancellation requests cooperatively,
- is idempotent per idempotency key, so a retried request reuses the job.

Application workers and scientific execution workers stay architecturally
distinct: the application worker submits a request and records the answer.

## Scheduling

Schedule expressions are an explicit, validated grammar — `every:<n>[m|h|d]`
(5-minute minimum), `daily:HH:MM`, `weekly:<dow>:HH:MM`,
`monthly:<1-28>:HH:MM` — evaluated in the schedule's IANA timezone. Firings
within a 5-minute grace window count as punctual; later slots follow the missed
policy. Concurrency policies decide whether a new firing may stack on a running
execution, and the catch-up limit bounds backlog replay.

## Compute nodes

Node selection filters by node class, queue, declared capability and resource
fit (CPU cores, memory, disk), requires the node to be schedulable (active,
healthy, spare capacity) and then picks least-loaded. Placement is a scheduling
decision only; it never influences a scientific result.

## Development adapter

`DevelopmentScientificAdapter` is a deterministic development/test double at the
scientific integration boundary. It is selected only by explicit configuration,
reports `is_development_adapter: true`, and is never production scientific
computation.

## Surfaces

REST: `/analyses`, `/analyses/{id}/configurations`, `/analysis-executions`,
`/jobs`, `/analysis-schedules`, plus `/administration/jobs` and
`/administration/compute-nodes` behind platform permissions.

UI: `/analyses` (list + definition), `/analyses/{id}` (versions, executions,
provenance), `/jobs` (durable work with attempt history). The browser renders
server answers; it authorizes nothing and computes no scientific result.
