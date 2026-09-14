# Evidence (Package 9)

Evidence is a first-class concept, separate from variants, annotations, criterion
evaluations, classifications and interpretations. This layer **stores and manages
what a source or a person stated**. It never decides what a statement means.

## Concepts

| Concept | What it is |
| --- | --- |
| Evidence source version | One registered release of one external or internal source: `(source_key, version)`, category, provider, release label, release/retrieval timestamps, schema version, checksum, what it is declared to supply, whether it states strength. |
| Evidence record | One statement about one variant: category, direction, strength, applicability, context (gene/transcript/condition/inheritance), verbatim source values, origin, provenance, version number. |
| Evidence delivery (ingestion batch) | One validated payload from one source version, identified by its content digest. |
| Validation finding | Why a claim in a delivery was not stored, or what was unusual about it. |
| Conflict | Two retained current records that disagree in direction, strength or applicability. Computed on read, never resolved, never stored as a decision. |

## Rules the implementation enforces

- **No classification.** No module in this layer states whether evidence satisfies
  an interpretation criterion or what a variant's classification is.
- **Sources are platform-governed.** Registering a version and moving it through
  `registered → active → deprecated → retired/invalidated` requires
  `platform.evidence_resource.administer`. Only `active` and `deprecated` versions
  may supply evidence.
- **Versions are never rewritten.** A corrected release is a new source version. A
  restated statement is a new evidence version that supersedes the previous one;
  the previous one stays readable with its original content.
- **Disagreement is preserved.** One source never overwrites another. A source
  changing its own mind is a new version, not a conflict with itself.
- **Values are never repaired.** A claim naming an undeclared category, a strength
  a source does not state, or a variant the platform cannot resolve is rejected
  and recorded as a finding.
- **Deliveries are idempotent.** The same payload from the same source stores
  nothing twice; a redelivery returns the original batch.
- **Origin is explicit.** `imported`, `retrieved`, `generated`, `human_entered`
  and `human_evaluated` stay distinguishable, so curated evidence can never be
  mistaken for source-delivered evidence.
- **Tenancy comes from the stored row.** Records without a workspace are platform
  reference evidence; workspace records are readable only within the caller's own
  grants, whatever identifiers the request carries.
- **Large deliveries stay outside the API.** Inline claims are capped; bigger
  batches are referenced as an artifact in object storage.

## REST surface (`/api/v1`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/evidence-sources` | Registered source versions. |
| GET | `/evidence-sources/{id}` | One source version. |
| GET | `/evidence-records` | Records in scope, optionally per variant/source/category. |
| GET | `/evidence-records/{id}` | One record. |
| POST | `/evidence-records` | Record evidence a person is stating. |
| POST | `/evidence-records/{id}/withdrawal` | Withdraw a record; content is unchanged. |
| GET | `/evidence-records/variants/{id}/history` | Every version, superseded included. |
| GET | `/evidence-records/variants/{id}/conflicts` | Retained disagreement, unresolved. |
| POST | `/evidence-deliveries` | Ingest one validated delivery. |
| GET | `/evidence-deliveries` | Delivery outcomes. |
| GET | `/evidence-deliveries/{id}/findings` | Why claims were refused. |
| POST | `/administration/evidence-sources` | Register a source version. |
| POST | `/administration/evidence-sources/{id}/state` | Move its lifecycle state. |

## Storage

Migration `0009_evidence_layer` widens `app.evidence_items` with source identity,
context, applicability, state, versioning and provenance columns, and adds
`app.evidence_ingestion_batches` and `app.evidence_validation_findings`. No table
was rebuilt and no earlier migration was replaced.

## UI

- `/admin/evidence` — source registry, lifecycle actions, what each source is
  declared to supply, and recent delivery outcomes.
- Variant browser — an evidence panel showing disagreement first, then every
  recorded version with its attribution and provenance.

## Limitations

- Artifact-backed (non-inline) deliveries are recorded and located, not parsed.
- Source registration is available through the API; the admin screen offers
  lifecycle actions rather than a full registration form.
