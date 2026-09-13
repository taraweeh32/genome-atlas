# Datasets, files, uploads, import and validation

This document describes the ingest domain as implemented in Package 4. It is the
reference for how a submitted file becomes a usable scientific input — and for the
several places where the platform deliberately refuses to guess.

## Entities

| Entity | Purpose |
| --- | --- |
| `Dataset` | A named container in exactly one scope: a workspace, or a project inside one. Holds no bytes. |
| `DatasetVersion` | One immutable submission of that dataset's content. Carries the declared build, the detected format, checksums and the source representation. |
| `FileArtifact` | One stored object belonging to a version: upload state, scan state, validation state, detected format, size, digest. |
| `UploadSession` | The server-issued permission to transfer bytes, and the gate that decides whether those bytes may become an input. |
| `ImportSession` | The record of a tabular import: detected format, confirmed mapping, provenance, decision. |
| `DatasetColumnMapping` | One source column and what a person decided it means (or what the platform merely suggested). |
| `ValidationRun` / `ValidationIssue` | A validator execution over a subject, and its findings with explicit severities and value semantics. |

## The ingest protocol

```text
create dataset ─▶ create version (draft)
                        │
                        ▼
        open upload session ──▶ short-lived transfer grant (PUT direct to storage)
                        │
                        ▼
              complete upload  ──▶ enqueues DATASET_VALIDATION (durable job)
                        │
                        ▼
   verify artifact: virus scan ─▶ structural inspection ─▶ checksum ─▶ validation
                        │
             ┌──────────┴───────────┐
             ▼                      ▼
        quarantined/rejected    version validated
                                    │
                        ┌───────────┴────────────┐
                        ▼                        ▼
              open import session          accept version  (explicit human act)
                        │
              confirm column mapping (human decision, recorded as such)
                        │
                        ▼
              submit import ──▶ DATASET_IMPORT job ──▶ validated, never auto-accepted
```

## Rules the implementation enforces

1. **Bytes never traverse the API.** Uploads and downloads are short-lived
   presigned grants. Storage keys are derived only from server-generated
   identifiers and are never returned to a client.
2. **A grant is not a capability.** Every download re-authorizes against the
   artifact's own scope; possessing a URL grants nothing beyond its lifetime.
3. **Declared is not verified.** A submitter's filename, size, format, digest and
   reference build are recorded as claims and checked against the stored bytes.
4. **Validation is not acceptance.** A passing validation leaves a version
   `validated`. Making it the dataset's current input is a separate action with
   its own permission and its own audit record.
5. **An accepted version is immutable.** Corrected data becomes a new version; the
   bytes an earlier result was produced from are never overwritten.
6. **Duplicates are reported, never resolved.** An identical upload may be
   legitimate; silently reusing an existing artifact would rewrite lineage.
7. **Semantics are never conflated.** `classify()` maps a source token to
   `missing`, `empty`, `null`, `na`, `unknown`, `not_applicable`, `zero`, `false`
   or `present`. Zero and false are real values; the other absent markers are not
   read as either. A column whose sampled values are all absent markers is
   *reported*, not assumed.
8. **Suggested and confirmed mappings are distinguishable forever**
   (`MappingOrigin.SYSTEM_SUGGESTED` vs `HUMAN_CONFIRMED`), in the row, in the API
   and in the UI.
9. **No scientific interpretation happens here.** Format detection, column
   mapping and structural validation are file handling. Normalization, allele
   interpretation, build verification and annotation belong to the scientific
   compute subsystem behind its versioned contract.

## Authorization

A dataset declares its own scope on its row. `resolve_scope()` in
`application/use_cases/data/dependencies.py` is the single place the scope-to-
permission mapping lives: a workspace dataset is governed by the `workspace.data.*`
permissions, a project dataset by the `project.data.*` permissions. Organization
membership alone never reaches into a project's data. Each response carries the
caller's `capabilities` for that resource as a *rendering hint only*; every
operation re-evaluates the permission server-side.

## Verification, quarantine and retrievability

`VerifyArtifact` runs inside a durable job. It scans, inspects a bounded prefix,
recomputes the digest and runs structural validation. An infected object is moved
under the `quarantine/` prefix and the session is quarantined. An artifact is
retrievable only when it is active, uploaded, scanned clean **and** validated
`valid`: an `invalid` artifact may be bytes that are not what was submitted.

## Jobs

Ingest work is durable and idempotent, never browser-side:

| Job kind | Handler | Trigger |
| --- | --- | --- |
| `DATASET_VALIDATION` | `VerifyArtifact` | completing an upload |
| `DATASET_IMPORT` | `ExecuteImport` | submitting a confirmed import |
| `MAINTENANCE` | `ExpireStaleUploadSessions` | scheduled operation |
