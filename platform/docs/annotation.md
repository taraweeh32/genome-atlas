# Annotation resources and annotation ingestion (Package 8)

The application governs annotation; it never performs it. No consequence
prediction, transcript selection, HGVS generation, liftover, frequency
computation or clinical inference exists anywhere in the application tree. What
lives here is identity, configuration, provenance, validation and storage of what
an external scientific tool declared.

## Architecture

```text
Annotation resource registry  ->  Annotation profile (versioned, immutable once used)
            |                                  |
            |                                  v
            |                  Annotation run  ->  durable job (Package 5)
            |                                  |
            |                                  v
            |                     scientific gateway (adapter boundary)
            |                                  |
            |                                  v
            +---------------->  annotation ingestion (validation + findings)
                                               |
                     +-------------------------+--------------------------+
                     v                                                    v
      Package 6 annotation rows (PostgreSQL)             artifacts / Parquet (object storage)
                     |
                     v
      Package 7 filter-field dictionary  ->  filtering and ranking
```

## Resource registry

An annotation resource version is `(resource_key, version)` plus provider,
category (`consequence`, `transcript`, `gene`, `functional`,
`external_database`, `other`), reference context, release label, schema version,
checksum/content identity, provenance, licensing and lifecycle state. No specific
external database is privileged: every source is just a registered resource.

A version is immutable. A correction is a new version, so historical annotation
results stay reproducible. Lifecycle transitions (`active`, `deprecated`,
`retired`, `invalidated`) change whether a version may be *used*; they never
change what an earlier run recorded.

Each resource version declares its annotation fields (key, label, value type,
missing semantics, allowed values, cardinality, filterability).

## Annotation profiles

A profile version pins the capability identity, the exact resource versions, the
engine identity, the reference context, required inputs, output field keys,
parameters and provenance requirements, and carries a `configuration_digest`. A
profile version that has been referenced by a run is frozen: further changes
create a new version.

## Runs and the scientific boundary

Requesting a run resolves the surface (result set or dataset version), takes
tenancy from that surface, freezes the profile version configuration onto the
run, and enqueues one durable `annotation_execution` job in the same transaction.
The worker builds a structured `ScientificExecutionRequest` — capability, input
artifact, reference context, resource versions, output requirements, provenance
context — and hands it to the existing scientific gateway. The web application
never passes a command line, script or arbitrary parameter to the scientific
node.

## Ingestion contract

A payload declares its contract version, run, resource identity and version,
engine/environment/container/node identity, reference assembly, parameters
digest, records and/or artifacts.

Blocking checks reject the whole payload: unsupported contract version, run
mismatch, missing or mismatched resource identity, unusable resource version,
checksum mismatch, reference-context mismatch, oversized inline batch.
Record-level checks reject only the offending record and record a finding:
missing or unlinkable variant, unknown origin, undeclared field, value type or
semantics mismatch, an "absent" value that still carries data. Repeated claims
inside one payload are dropped, not stored twice.

Values are never repaired. `missing`, `unknown`, `na`, `zero` and `false` stay
distinct: an absent value is stored as `null` beside its `value_semantics`, and
`imported`/`retrieved`/`generated` origin is preserved as declared. Accepted
values are written as ordinary Package 6 annotation rows, each carrying its own
resource identity and version, so conflicting values from different resources or
versions coexist.

Ingestion is idempotent by payload digest: a redelivered payload returns the
original result version rather than creating a second one.

## Result versioning and provenance

An annotation result version records counts (declared, stored, rejected), field
keys, completeness, payload digest, checksum and analytical location, and never
overwrites an earlier version — a newer resource version or re-run produces a new
result version and marks the previous one superseded. Counts, checksums,
locations and provenance are written once at ingestion; only lifecycle state and
the supersession pointer move afterwards.

Every result version is traceable to: input surface (result set or dataset
version), annotation run, annotation resource and version, profile version and
configuration digest, scientific execution, engine/environment/container/node
identity, reference assembly, contract version, ingestion timestamp and the
actor or system execution context.

## Package 7 integration

Fields declared by usable resource versions are projected into the filter-field
dictionary, each carrying stable field id, label, type, description, source
resource key and version, supported operators and availability. The dictionary
version includes a digest of the extended field set, so an execution can never
record a dictionary version it was not validated against. The dictionary is
cached briefly and refreshed before filtering requests; filtering consumes these
fields without knowing anything about how they were produced. No annotation field
is hardcoded in the frontend.

## Large data

PostgreSQL holds metadata and control state. Large annotation output stays in
object storage as artifacts with Parquet/DuckDB analytical locations. Inline
record batches are bounded; oversized batches must be delivered as artifacts, and
annotation rows are never inlined in ordinary API responses.

## APIs

Reads: `/api/v1/annotation-resources`, `/annotation-resources/{id}`,
`/annotation-fields`, `/annotation-profiles`, `/annotation-profiles/{id}`,
`/annotation-runs` (+ `/{id}`, `/{id}/results`), `/annotation-results` (+
`/{id}`).
Actions: `POST /annotation-runs`, `POST /annotation-runs/{id}/cancel`.
Platform administration: `/administration/annotation-resources` (register,
`/{id}/state`) and `/administration/annotation-profiles` (create, versions,
publish, archive).

Ordinary users read annotation status and request runs inside their own
workspace; only a platform administrator registers resources, moves lifecycle
state or manages profiles.

## Migration

`0008_annotation_resources` creates `annotation_resource_fields`,
`annotation_profiles`, `annotation_profile_versions`, `annotation_runs`,
`annotation_result_versions` and `annotation_validation_findings`, and re-issues
the `jobs.kind` / `scheduled_jobs.job_kind` check constraints for the two new job
kinds.
