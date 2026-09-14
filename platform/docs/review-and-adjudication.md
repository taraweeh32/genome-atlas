# Interpretation, Human Review and Adjudication (Package 11)

Package 10 produces an *automated suggestion*. Package 11 records what people
decided about it. These are different records with different authorities.

## Distinct states, deliberately not merged

| Concept | Where it lives | Written by |
| --- | --- | --- |
| Automated classification | `automated_classifications` (Package 10) | rules engine, behind the scientific boundary |
| Reviewer decision | `review_decisions` (append-only) | an assigned reviewer |
| Adjudicated decision | `interpretation_versions` with `decision_role = adjudicated_decision` | an adjudicator |
| Final interpretation | the finalized `interpretation_version` | the finalizer |

An interpretation version pins, by reference, the exact ruleset version, the
exact criterion evaluations (`interpretation_version_criteria`) and the exact
evidence items (`interpretation_version_evidence`). Nothing is copied into a
second criterion or evidence model.

## Lifecycles

Interpretation: `draft → automated | in_review | withdrawn`,
`in_review → adjudication | approved`, `approved → finalized`,
`finalized → superseded` (only by opening a successor), `superseded` and
`withdrawn` terminal.

Review: `not_started → assigned → in_progress → submitted → accepted | rejected |
escalated`, with `withdrawn` available until submission and terminal thereafter.

## Rules enforced by the backend

- **Attribution.** Every decision carries its reviewer, round, timestamp and
  rationale. Decisions are inserted, never updated or deleted.
- **Disagreement is preserved.** When submitted reviewers propose different
  classifications the interpretation moves to `adjudication` and both positions
  remain readable. Nothing is averaged and no tie is broken automatically.
- **A reviewer does not adjudicate their own disagreement.** Reviewing,
  adjudicating and finalizing are three permissions
  (`project.interpretation.review`, `.adjudicate`, `.finalize`).
- **Optimistic concurrency.** A reviewer decision and a finalization carry the
  version number the actor was looking at; a stale one is refused with a conflict
  rather than silently applied over newer work.
- **Finalized means closed.** `finalize_version` is the only update, guarded by
  `finalized_at IS NULL`. A correction calls `/reclassify`, which supersedes the
  record and opens a successor for the same question. The partial unique index
  `uq_interpretations_open_context` allows exactly one *open* context per
  project, variant and condition while keeping superseded ones in place.
- **Tenancy from the stored row.** Every endpoint takes an interpretation
  identifier and resolves workspace and project from the persisted record; a
  known identifier cannot become a cross-tenant read. Missing and unauthorized
  both surface as not-found.

## Surfaces

`POST /api/v1/interpretations`, `GET /api/v1/interpretations`,
`GET|POST .../{id}`, `.../versions`, `.../reviewers`, `.../decisions`,
`.../submit-review`, `.../adjudicate`, `.../finalize`, `.../reclassify`.

Frontend: `/interpretations` shows the context, the automated suggestion, the
version history with decision roles, reviewer assignments, the full decision
history including overruled positions, and the review, adjudication, finalization
and reclassification actions. The browser evaluates no criterion and derives no
classification.
