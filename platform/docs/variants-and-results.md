# Variants, Result Surfaces and the Scientific Data Boundary

This document describes the Package 6 surface: how scientific output enters the
platform, how it is stored, how it is read, and where the boundary between the
application and the scientific subsystem lies.

## 1. What the platform does and does not do

The platform records, verifies, authorizes and presents scientific content. It
does not produce it. There is no normalization, liftover, HGVS construction,
consequence calculation, population-frequency computation, annotation retrieval,
clinical-evidence evaluation, ACMG criterion assignment, classification, filtering
or ranking anywhere in the application tree. A test
(`tests/application/test_scientific_boundary.py`) enforces this and names every
module allowed to touch scientific vocabulary, with a written rationale for each.

Every value stored here was *declared* by the scientific subsystem through a
versioned contract. The platform attributes it, keeps it immutable and refuses to
present it as anything other than what was declared.

## 2. Ingestion contract

`app/scientific/results.py` defines contract version 1:

- `VariantIngestionPayload` — source and canonical representations, external
  identifiers, transcript contexts, sample observations, annotations, population
  frequencies and clinical assertions, each carrying its own attribution
  (originating resource, resource version, engine, engine version, execution).
- `ResultPayload` — a result surface: result key, analytical location, row count,
  column schema, completeness and artifact claims.
- `is_development_payload` marks output produced by the development adapter. The
  flag travels through persistence, the API and the UI. A stub result is never
  presentable as a validated scientific result.

`app/domain/variant/ingestion.py` validates payloads *structurally*: required
attribution, contract version, provenance completeness, consistent representation
shape. It never judges scientific correctness, because that is not the
application's competence.

## 3. Delivery is a durable job

Submitting a payload does not materialize a readable surface. `SubmitResultPayload`
records the request idempotently and enqueues a `result_ingestion` job.
`MaterializeResultSet`, executed by an application worker, then:

1. verifies each storage-backed artifact exists in object storage;
2. verifies its checksum when the engine declared one (mismatch → `rejected`);
3. verifies the analytical surface is structurally readable;
4. moves the result set `pending → generating → validated → available`, or to
   `failed` with a recorded failure code.

Analytical-only artifacts stay `registered`. Redelivery of the same idempotency
key returns the existing request rather than duplicating work. Application workers
and scientific execution workers remain architecturally distinct.

## 4. Result-set lifecycle versus content

Content is immutable. Lifecycle is not:

```text
pending → generating → validated → available → superseded
                    ↘ failed              ↘ invalidated
```

`invalidate` (platform administrators only) withdraws a surface from use and
records a reason; `supersede` records that a newer surface replaced it. Neither
alters a single recorded value, and both remain visible so history stays legible.
Readable states are `available` and `superseded`.

## 5. Reading results

- `GET /api/v1/result-sets` — result sets in an authorized workspace or project.
- `GET /api/v1/result-sets/{id}` — the surface with artifacts, provenance and the
  server's own `capabilities` list.
- `GET /api/v1/result-sets/{id}/content` — a **bounded** window
  (`offset`/`limit`, clamped server-side to 500 rows) read through DuckDB over the
  stored Parquet surface. No filtering, ranking or interpretation is applied.
- `POST /api/v1/result-sets/{id}/artifacts/{artifact_id}/download` — a short-lived
  presigned grant. Bytes never pass through the platform API.
- `POST /api/v1/result-sets/{id}/supersede`, and
  `POST /api/v1/administration/result-sets/{id}/invalidate`.

## 6. Variant identity

Canonical identity is: reference-genome resource, canonical contig, position,
reference allele, alternate allele, variant class, and the normalization state and
version under which those were produced. `normalization_unavailable` is a first
class state: a record whose normalization failed is stored with its failure reason
and is never presented as normalized.

Source representations are preserved verbatim beside canonical ones, including
unresolved rows that resolved to no canonical variant. The platform never
overwrites what a submitter provided.

Variants are read through one authorized dataset version:

- `GET /api/v1/variants?dataset_version_id=…` (optional contig and position
  bounds, applied server-side);
- `GET /api/v1/variants/{id}?dataset_version_id=…` for every recorded context.

Knowing a variant identifier grants nothing.

## 7. Data semantics

Missing, zero, false, unknown and not-reported are distinct. Every annotation,
frequency, clinical assertion and genotype value carries a `value_semantics`
field beside the typed value slots. When nothing was reported, the value is
`null` and the semantics say why. The API preserves this, and the UI displays the
semantics rather than substituting `0`, `false` or an empty string.

Imported, computed, automated and human-originated content stay distinguishable
through the `origin` recorded on every context row.

## 8. Authorization

Result metadata reads, content reads, artifact downloads, ingestion and variant
reads are separate scoped permissions, checked server-side at platform, workspace
and project scope. Refusals for out-of-scope resources are indistinguishable from
"does not exist". The frontend renders the server's `capabilities`; it never
computes a permission.

## 9. Frontend surfaces

- `/results` — result sets in the active workspace, with state, completeness,
  readability and the development-payload marker.
- `/results/[resultSetId]` — provenance chain (missing entries shown as missing),
  artifacts with download grants, and a bounded content window.
- `/variants` — dataset-version-scoped variant table plus a per-variant context
  panel: source representations, annotations, frequencies, transcript contexts,
  clinical assertions and sample observations, each with its attribution.

## 10. Tests

`tests/results/test_result_surfaces.py` (18 tests) covers delivery, idempotency,
verification, checksum mismatch, missing artifacts, unreadable surfaces,
unattributed refusal, unsupported contract versions, bounded reads, tenant
isolation, download grants, invalidation and supersession.
`tests/results/test_variant_records.py` (6 tests) covers canonical/source
recording, redelivery, unresolved records, value semantics, per-context
attribution and cross-tenant refusal. `tests/api/test_result_endpoints.py` (10
tests) covers the transport surface, and `tests/frontend` equivalents live in
`platform/frontend/tests/result-client.test.ts`.
