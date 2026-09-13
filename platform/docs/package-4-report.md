# Package 4 report — datasets, files, uploads, import and validation

Packages 1 (foundation), 2 (persistence baseline) and 3 (identity, authorization,
tenancy) are preserved. The Package 2 migration-hardening item remains
deliberately deferred and is documented in section 24. No architecture was
redesigned, no requirement removed, and no scientific algorithm was implemented.

---

## 1. Scope delivered

Dataset containers in workspace and project scope; immutable dataset versions;
file artifacts on S3-compatible storage; server-issued upload sessions with
short-lived transfer grants; durable verification (virus scan, structural
inspection, checksum recomputation, structural validation); quarantine;
duplicate reporting; explicitly authorized download grants; tabular import
sessions with human-confirmed column mapping; validation runs and findings with
explicit value semantics; version acceptance and rejection as a separate human
decision; retention-aware soft deletion; the REST API for all of the above; the
dataset frontend surfaces; audit, activity and provenance; job enqueue and
handlers; tests; documentation.

Not in scope and not faked: analyses, filtering and ranking, variant storage in
Parquet, annotation, evidence, ACMG interpretation, reporting, notifications,
search. Nothing in this package interprets genomic content.

## 2. Domain model

Framework-free entities in `domain/data/entities.py`: `Dataset`,
`DatasetVersion`, `FileArtifact`, `UploadSession`, `ImportSession`,
`DatasetColumnMapping`, `ValidationRun`, `ValidationIssue`. Supporting modules:
`domain/data/formats.py` (format and compression detection from magic bytes and
filenames), `domain/data/mapping.py` (the concept vocabulary and its refusal to
accept ambiguous declarations), `domain/data/semantics.py` (explicit value
semantics), `domain/data/storage.py` (the storage key layout).

## 3. Scope and ownership

A dataset lives in exactly one scope and declares it on its row: a workspace, or
a project inside a workspace. The request never decides the scope — the stored
resource does. Creator and owner remain distinct fields.

## 4. Storage key layout

`uploads/{workspace_id}/{dataset_id}/{dataset_version_id}/{file_artifact_id}` and
`quarantine/{workspace_id}/{file_artifact_id}`. Every component is a
server-generated prefixed identifier; no filename, path or client-supplied string
ever enters a key. Keys are never returned by the API, and a key is not a
capability: retrieval is authorized first, then presigned.

## 5. Upload protocol

Three steps: open a session (server records the submitter's claims and issues a
short-lived PUT grant), transfer the bytes directly to object storage, declare the
transfer finished. Completion moves the session and artifact through their
intermediate states and enqueues verification. A grant that expires without a
transfer is expired by the maintenance handler, not by a client.

## 6. Verification

`VerifyArtifact` runs in a durable job: virus scan, structural inspection of a
bounded prefix, digest recomputation compared against the declared value, then
structural validation. An infected object is moved under `quarantine/`. A
mismatch between declared and stored facts is a finding, never a correction.

## 7. Retrievability

An artifact is retrievable only when it is active, uploaded, scanned clean and
validated `valid`. During Package 4 this was tightened: an `invalid` artifact is
no longer retrievable, because it may be bytes that are not what was submitted.

## 8. Duplicate handling

An identical digest is reported as a duplicate relation with the artifact it
matches. It is never merged, deduplicated or silently reused: an identical upload
may be legitimate, and reusing an artifact would rewrite lineage.

## 9. Immutability and versions

A version is the unit of immutability. Once accepted it cannot receive files or
change its content; corrected data becomes a new version, and the superseded one
keeps its identity so historical results stay reproducible.

## 10. Validation is not acceptance

Verification and import leave a version `validated`. Acceptance is a separate
endpoint, a separate permission and a separate audit record.
`acceptance_blocked_reason` is derived server-side, returned for display, and
re-derived by the accept endpoint — the UI cannot disagree with it.

## 11. Import and column mapping

An import session records the detected format, the platform's suggested mappings
and then the human-confirmed mapping. `MappingOrigin` keeps suggestion and
confirmation permanently distinguishable, in the row, in the API and on screen.
`mapping_metadata` retains the confirmed configuration verbatim for provenance
while the mapping rows make it queryable.

## 12. Value semantics

`classify()` maps a token to `missing`, `empty`, `null`, `na`, `unknown`,
`not_applicable`, `zero`, `false` or `present`. Zero and false are real values.
During Package 4 the import validator was corrected to decide "usable" by these
semantics rather than by whether a cell contained characters, so a column of `NA`
markers is reported rather than treated as populated.

## 13. Validation findings

Every finding carries severity, category, code, message, locator, the observed
value, and the explicit semantics of that value. Blocking findings refuse the
subject; errors, warnings and notes are retained and surfaced. Findings are never
discarded to make an input pass.

## 14. Jobs

`DATASET_VALIDATION` → `VerifyArtifact`, `DATASET_IMPORT` → `ExecuteImport`,
`MAINTENANCE` → `ExpireStaleUploadSessions`, wired in `workers/handlers.py` with a
worker request context of its own. Enqueue is transactional with the state change
that justifies it. Claiming, leases, heartbeats and stale recovery remain the job
package's scope and were not invented here.

## 15. API surface

`POST/GET /datasets`, `GET/PATCH/DELETE /datasets/{id}`,
`POST /datasets/{id}/state`, `POST/GET /datasets/{id}/versions`,
`GET /datasets/{id}/imports`, `GET /dataset-versions/{id}`,
`POST /dataset-versions/{id}/decision`, `POST /dataset-versions/{id}/uploads`,
`POST /uploads/{id}/complete`, `POST /uploads/{id}/cancel`,
`POST /file-artifacts/{id}/download`, `POST /file-artifacts/{id}/imports`,
`GET /imports/{id}`, `PUT /imports/{id}/mapping`, `POST /imports/{id}/submit`,
`POST /imports/{id}/abandon`, `GET /validation/runs`,
`GET /validation/runs/{id}`. All under `/api/v1` with OpenAPI documentation and
the shared error envelope.

## 16. Authorization and isolation

`resolve_scope()` is the single mapping from a resource's declared scope to the
required permission, so no use case re-implements it. Workspace datasets require
`workspace.data.*`; project datasets require `project.data.*`; organization
membership alone never reaches into project data. Knowing an identifier yields a
refusal that discloses nothing about the resource.

## 17. Frontend

`/datasets` lists the active workspace's datasets and creates them; `/datasets/{id}`
shows versions, files, verification state, validation findings, acceptance and the
import flow. The browser computes a digest as a claim, transfers bytes straight to
storage with the grant, and never receives a storage key or a session cookie on
the storage origin. Server-supplied `capabilities` decide which controls render;
`acceptance_blocked_reason` and `submission_blocked_reason` are displayed
verbatim. Absent values are rendered as what they are, never as `0` or `false`.
Loading, empty, error and refusal states are explicit, and no screen contains
hardcoded scientific data.

## 18. Administration

No new administrative authority was introduced. Dataset governance surfaces
(storage reconciliation, retention administration) remain the administration
package's scope and were not stubbed.

## 19. Audit, activity and provenance

Distinct as before. Audit records the security-relevant decision (upload refused,
version accepted, download granted). Activity records the user-visible event.
Provenance is written onto the version and import session: input artifacts,
digests, detected formats, validator name and version, importer version, the
confirmed mapping and the validation run that examined it. During Package 4 the
lineage write was corrected to record the examining run whether or not that run is
what moved the version to `validated`, and a rejected import contributes nothing.

## 20. Concurrency and integrity

Optimistic versioning on datasets, versions and import sessions; a unique
constraint tying one upload session to one storage key so two sessions cannot race
for the same object; state transitions validated centrally by
`require_transition`. Two lifecycle gaps found and fixed: a created session now
passes through `uploading` before `uploaded`, and a created session may fail
before any byte arrives.

## 21. Configuration

`upload_url_ttl_seconds` (default 900) and `download_url_ttl_seconds` (default
300) are validated settings. `feature_development_file_scanner` exists for local
work and `build_scanner` never selects the development scanner in a
production-like environment.

## 22. Testing

224 backend tests and 27 frontend tests pass; type checks and lint are clean.
New coverage: dataset creation, naming conflicts, tenant isolation, archiving and
soft deletion; version immutability and acceptance gating; transfer grants,
completion, verification, quarantine, download grants, cancellation, stale-session
expiry and duplicate reporting; import sessions, column mapping origin, structural
validation and absent-value reporting; transport tests over the real app for
authentication, CSRF, enum validation, cross-tenant refusal and the guarantee that
no storage key appears in a response; frontend tests for scoped listing, CSRF on
state-changing calls, the storage transfer carrying no session credentials, mapping
confirmation payloads and download grants.

## 23. Defects found and fixed

1. `UploadSessionState.CREATED` could not reach `FAILED`; a grant that fails
   before any transfer had no valid state.
2. A created session skipped `UPLOADING` on completion.
3. `NotFoundError` did not support the two-argument form the use cases used.
4. `is_retrievable` accepted an `invalid` artifact.
5. The import validator treated absent markers such as `NA` as populated values.
6. Import lineage was recorded only when that run also changed the version state.
7. `argon2-cffi` was imported since Package 3 without being declared as a
   dependency.

## 24. Deferred items

1. **Package 2 migration hardening** — still deferred, unchanged, deliberately not
   bundled into Package 4.
2. **Mail transport** — unchanged from Package 3.
3. **Duplicated infrastructure instances** in the container (`TokenHasher`,
   `SystemClock`) — unchanged, harmless, should be collapsed.
4. **Job claiming, leases and stale recovery** — belongs to the job package; this
   package only enqueues and provides handlers.
5. **Parquet/DuckDB materialization of imported records** — the analytical
   boundary exists but populating it is the analytical package's scope.
6. **Storage reconciliation and retention execution** — administration scope.
7. **Lint debt inherited from earlier packages** (`UP047`, `RUF012`, `BLE001`,
   stale `noqa` directives) remains untouched to keep this package's diff
   reviewable.

## 25. Conflicts found

None. No boundary was simplified, no authorization moved to the frontend, no
scientific algorithm introduced, no fake data added, and no mock is presented as a
production implementation.
