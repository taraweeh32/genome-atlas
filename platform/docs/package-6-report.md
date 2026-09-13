# Package 6 — Variant Records, Result Surfaces & the Scientific Data Boundary: Delivery Report

## 1. Scope delivered

Variant identity and variant context recording, result-set and artifact domains,
the versioned scientific ingestion contract, structural ingestion validation,
persistence and migration `0006`, durable result-ingestion jobs with verification,
the analytical read boundary over Parquet/DuckDB, a bounded result-content API,
artifact download grants, administrative invalidation, supersession, variant read
APIs, the `/results` and `/variants` frontend surfaces, documentation and tests.

## 2. What was explicitly not implemented

No VEP, normalization, liftover, HGVS, consequence calculation,
population-frequency computation, annotation retrieval, clinical-evidence
evaluation, ACMG criteria, classification, filtering, ranking or scientific
inference exists in application code. Interpretation, review, adjudication and
reporting remain for later packages. Filtering and ranking are deliberately absent
from the result read path.

## 3. Architectural position

The application is a recording, verification, authorization and presentation
layer around scientific output. Scientific content crosses the boundary only as an
explicit versioned payload (`app/scientific/results.py`, contract version 1), and
`tests/application/test_scientific_boundary.py` names every module permitted to
handle that vocabulary together with the rationale for each allowance.

## 4. Domain model

`app/domain/variant/identity.py` defines `CanonicalVariantIdentity` and
`ContigLabel`. `entities.py` defines `VariantRecord`, `VariantRepresentation`,
`VariantSourceRepresentation`, external identifiers, gene/transcript references,
transcript contexts, `SampleRecord`, `SampleObservation`,
`VariantAnnotationRecord` with `AnnotationValue`, `PopulationFrequencyRecord`,
clinical assertions and dataset-version membership. `results.py` defines
`ResultProvenance`, `ResultSetRecord`, `ResultArtifactRecord` and
`ResultIngestionRequest`. All are immutable value objects with explicit lifecycle
methods.

## 5. Variant identity

Identity is reference-genome resource, canonical contig, position, reference
allele, alternate allele, variant class, normalization state and normalization
version. Canonical variants are shared across dataset versions; membership is a
separate append-only link.

## 6. Source representation preservation

Every submitted row is stored verbatim with its record key, contig, position,
alleles and identifier. Unresolved rows keep a null canonical variant and their
`normalization_failure_reason`. Source data is never overwritten and links are
guarded against repointing.

## 7. Normalization states

`normalized`, `not_normalized` and the explicit `normalization_unavailable` are
distinct. An unavailable normalization is displayed as such throughout the API and
UI; it is never rendered as a normalized identity.

## 8. Attribution on every context

Annotations, frequencies, transcript contexts, clinical assertions and
observations each carry origin, source resource, resource version, engine resource,
engine version and scientific execution where applicable. A frequency claimed as
imported is refused without its resource and version.

## 9. Value semantics

`ValueSemantics` (`present`, `missing`, `null`, `empty`, `na`, `unknown`) sits
beside typed value slots. Missing, zero, false and unknown are never conflated at
any layer: contract, domain, persistence, API or UI.

## 10. Result sets

A result set is one readable surface produced by one execution, keyed by result
key within a project, carrying completeness, origin, row count, column schema and
its full provenance.

## 11. Result-set lifecycle

`pending → generating → validated → available → superseded`, with `failed` and
`invalidated` branches. Transitions are backend-owned and validated against an
explicit transition table; `available()` only proceeds from `validated`.

## 12. Content immutability

Invalidation and supersession change lifecycle state and record a reason or
successor. Neither mutates recorded scientific content, and neither removes the
surface from history.

## 13. Artifacts

Artifacts carry kind, format, media type, size, checksum algorithm and value, row
count, column schema and state (`declared`, `registered`, `accepted`, `missing`,
`rejected`). Artifact state is derived from verification, never from a client
claim.

## 14. Ingestion requests

`ResultIngestionRequest` records delivery idempotently. Redelivery of the same key
returns the existing request. Requests carry their own state so a failed delivery
is legible rather than silently absent.

## 15. Durable ingestion jobs

`JobKind.RESULT_INGESTION` is dispatched to `NodeClass.APPLICATION_WORKER` on the
`import` queue and handled by `app/workers/result_handlers.py`. Materialization is
idempotent, so retries and duplicate deliveries converge.

## 16. Verification

Storage-backed artifacts are checked for existence, then checksum when one was
declared (mismatch → `rejected`). The analytical surface is checked for structural
readability. Any failure moves the result set to `failed` with a recorded code;
nothing partially verified becomes readable.

## 17. Analytical read boundary

`AnalyticalReadService` (`app/application/ports.py`) and `DuckDbResultReader`
(`app/infrastructure/analytics/result_reader.py`) provide `describe` and a bounded
`read_page` over Parquet via DuckDB, executed on a worker thread, with location
validation and a 500-row page ceiling. The reader performs no filtering, ranking
or interpretation.

## 18. Bounded content reads

`ReadResultPage` clamps `offset` to ≥ 0 and `limit` to 1–500 regardless of the
request, and refuses surfaces that are not in a readable state.

## 19. Artifact downloads

`AuthorizeArtifactDownload` re-authorizes, requires an accepted artifact and
issues a short-lived presigned URL. Bytes flow from object storage to the client;
the platform API never proxies them.

## 20. Development adapter honesty

`is_development_payload` is stored, returned by every content and metadata
response and rendered prominently in the UI. No mock is presentable as a
production scientific implementation.

## 21. Provenance

Each result set records analysis execution, scientific execution, configuration
version, engine resource and version, environment version, container image digest,
node identity, reference genome resource, resource identities and parameters
digest, plus `is_attributable`. Missing provenance is shown as missing and never
inferred.

## 22. Authorization

Separate scoped permissions for result metadata read, result content read,
artifact download, result ingestion and variant read, granted to platform
administrator, organization member, project viewer/analyst/reviewer and personal
workspace roles. Every use case re-authorizes server-side; `capabilities` are
rendering hints only.

## 23. Tenant isolation

Result and variant reads resolve through an authorized workspace, project or
dataset version. Cross-tenant access is refused indistinguishably from
non-existence, which is asserted by tests at both the use-case and API layers.

## 24. Persistence

`models/variant_results.py` adds `VariantRepresentation`,
`DatasetVersionVariant`, `ResultArtifact` and `ResultIngestionRequest`; existing
models were extended for scientific origin, execution attribution, provenance,
normalization vocabulary, completeness and lifecycle lineage. Migration
`0006_variant_results` creates the tables, widens vocabulary checks and adds the
foreign keys.

## 25. Repositories

Ports live in `app/application/repositories.py`; SQL implementations in
`repositories/variants.py` and `repositories/results.py` are append-only and
idempotent, with version-checked writes for result sets. In-memory doubles in
`tests/support/variant_memory.py` mirror idempotency, tenant membership,
append-only behaviour and optimistic concurrency.

## 26. Application use cases

`use_cases/results/`: `dependencies.py` (services, scoped permission pairs, scope
resolution), `ingestion.py` (`SubmitResultPayload`, `MaterializeResultSet`),
`reads.py` (listing, detail, bounded content, download grants, invalidation,
supersession) and `variants.py` (`IngestVariantPayload`, variant listing and
detail).

## 27. API surface

Three routers: `/result-sets`, `/variants` and `/administration/result-sets`.
Handlers are thin and delegate to use cases. `schemas/results.py` and
`result_mapping.py` map one-directionally, preserve nulls and semantics, expose
provenance and never leak internal worker custody fields.

## 28. Administrative control

Invalidation lives on the administration router and is restricted to platform
administrators, with a mandatory reason, an audit record and no effect on content.

## 29. Frontend

`/results`, `/results/[resultSetId]` and `/variants` were added, plus
`src/lib/result-types.ts` and client methods. Surfaces are dense, keyboard- and
screen-reader-friendly, render explicit loading/empty/error states, show
server-declared capabilities and readability, and display value semantics instead
of substituting values. Navigation now marks Results and Variants available.

## 30. Observability and audit

Ingestion, materialization outcomes, download authorization, invalidation and
supersession emit domain events and audit records; correlation IDs flow request →
job → worker → artifact. Scientific content is not logged.

## 31. Data semantics preserved

Source versus canonical, imported versus computed versus human, present versus
missing versus unknown, and lifecycle versus content are all separately
represented. No layer collapses them.

## 32. Tests

Backend: `tests/results/test_result_surfaces.py` (18),
`tests/results/test_variant_records.py` (6), `tests/api/test_result_endpoints.py`
(10), plus the extended scientific-boundary guard. Frontend:
`tests/result-client.test.ts` (6) and the updated navigation test.

## 33. Verification performed

Backend suite: 306 passed. Frontend: 39 tests passed, `tsc --noEmit` clean,
`next lint` clean.

## 34. Known deferred items

Package 2 migration hardening, mail transport, duplicate `TokenHasher`/
`SystemClock` instances and inherited lint debt remain open. Variant ingestion
resolves samples through a single 1000-row page, which needs a paginated design
before large cohort ingestion. Server-side filtering and ranking over result
surfaces are intentionally deferred to their own package.

## 35. Conflicts found

None. Every Package 6 requirement was implementable within the locked stack and
the stated boundaries.
