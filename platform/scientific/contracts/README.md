# Scientific Integration Contract

**The scientific compute subsystem is independently deployable and is not
implemented inside the normal application domain.**

This directory holds the language-neutral description of the boundary between
the application and the scientific compute subsystem. The application-side
Python types live in `backend/app/scientific/contracts.py`; the scientific
subsystem is a separate deployment with its own repository/image lifecycle and
its own independently versioned tools and reference resources.

## Boundary responsibilities

| Application | Scientific subsystem |
| --- | --- |
| Owns workspaces, projects, datasets, jobs, review, reports | Owns all genomic computation |
| Submits execution requests with artifact references | Reads inputs, writes artifacts |
| Stores artifact references + provenance | Declares engine/environment/reference identity |
| Maps failures into the API error taxonomy | Returns structured scientific failures |

The application NEVER contains: VEP invocation, variant normalization,
annotation algorithms, ACMG rule logic, evidence algorithms, pipeline
orchestration internals, clinical-resource processing or population-frequency
computation.

## Interface (HTTP shape expected by `adapters/http.py`)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | reachability probe |
| `GET` | `/capabilities` | capability discovery + engine/environment/reference identity |
| `POST` | `/executions` | submit a scientific execution request |
| `GET` | `/executions/{execution_id}` | poll execution status/result |

### `GET /capabilities`

```json
{
  "engine": { "engine_id": "vep-engine", "engine_version": "1.4.2", "build_revision": "abc123" },
  "environment": { "environment_id": "sci-env", "environment_version": "2026.01", "container_digest": "sha256:..." },
  "capabilities": [
    { "capability_id": "variant.annotate", "capability_version": "3", "description": "..." }
  ],
  "reference_resources": [
    { "resource_id": "gnomad", "resource_version": "4.1", "genome_assembly": "GRCh38", "checksum": "sha256:..." }
  ]
}
```

### `POST /executions`

```json
{
  "capability_id": "variant.annotate",
  "capability_version": "3",
  "correlation_id": "3f2a...",
  "inputs": [{ "artifact_id": "art_1", "kind": "vcf", "storage_uri": "s3://bucket/key" }],
  "parameters": {},
  "requested_by_execution_id": null
}
```

### Execution response

```json
{
  "execution_id": "exec_1",
  "status": "accepted | running | succeeded | failed | cancelled",
  "correlation_id": "3f2a...",
  "artifacts": [{ "artifact_id": "art_2", "kind": "annotated-parquet", "storage_uri": "s3://bucket/key", "checksum": "sha256:..." }],
  "provenance": { "engine": {...}, "environment": {...}, "reference_resources": [...], "started_at": "...", "completed_at": "...", "parameters_digest": "..." },
  "failure": null
}
```

### Failure

```json
{ "code": "reference_resource_unavailable", "message": "...", "retryable": true, "details": {} }
```

## Invariants

1. Artifacts are passed by reference (object-storage URI), never inlined.
2. Every execution carries the caller's `correlation_id` end to end.
3. Every successful execution returns provenance identifying engine,
   environment and reference resources.
4. The subsystem may run on any number of independent nodes; the application
   makes no assumption about in-process execution or node locality.

## Development adapter

`backend/app/scientific/adapters/development.py` is **DEVELOPMENT ONLY**,
deterministic, sits behind this same contract, and refuses to initialize when
`APP_ENVIRONMENT=production`. It is not scientifically valid and must never be
cited as evidence of scientific correctness.
