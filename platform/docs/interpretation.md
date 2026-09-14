# Interpretation Rulesets & Automated Classification (Package 10)

The rules engine is an independently identifiable scientific component reached
only through the existing scientific boundary. The web application registers and
governs rulesets, submits structured interpretation requests, and stores the
structured results. It never evaluates a criterion, never combines criteria into a
classification, and never renders a classification the browser computed.

## Concepts and their separation

| Concept | Meaning | Never conflated with |
| --- | --- | --- |
| Interpretation ruleset | Versioned guideline representation: criteria, permitted strengths, combination rules, provenance, configuration identity | An unversioned table of `if` statements |
| Criterion evaluation | One criterion, its strength, its evidence references, rationale, origin, ruleset version, timestamp | Evidence itself (Package 9) |
| Automated classification | Engine-produced suggestion combining criterion evaluations under one ruleset version | A reviewer decision or a final interpretation (Package 11) |
| Benchmark case / run | Controlled input plus recorded observed outcome | A clinical accuracy claim |

`decision_role` is carried on every classification. Package 10 only ever produces
the automated role.

## Ruleset registry

A ruleset version carries `ruleset_key` + `version`, display name, guideline
source and citation, publication reference and year, specification scope
(`platform`, `gene`, `gene_condition`), optional gene/condition context,
combination strategy (`criteria_combination` or `point_based`), effective dates,
capability and engine identity, genome assembly, configuration digest, and its
declared criteria and combination rules.

Criteria are represented independently of any one guideline table: each has a
family (PVS, PS, PM, PP, BA, BS, BP), direction, default strength, permitted
strengths, evidence categories and an evidence requirement. Modified criterion
strengths, ClinGen gene/disease specifications, point-based and future frameworks
are expressed as new ruleset versions, not as code changes.

Lifecycle: `draft → active → deprecated → retired`, plus `invalidated`. A version
is never edited in place. A respecification is a new version, so a historical
classification naming an earlier version stays reproducible.

## Evaluation flow

1. `POST /api/v1/classification-evaluations` records a requested evaluation with
   the variant, ruleset version, evidence references, context and input digest.
2. A durable job (`classification_evaluation`) submits a structured
   `ScientificExecutionRequest` through the existing gateway — capability,
   ruleset identity, evidence references, reference context, output requirements
   and provenance context. No command line, script or arbitrary parameter is ever
   passed to a scientific node.
3. Returned criterion evaluations and the combined classification are ingested
   (`classification_ingestion`), validated against the ruleset's declared criteria
   and permitted strengths, and stored with engine, environment, node, execution,
   contract and digest provenance.
4. A re-evaluation never overwrites: it stores a new classification version and
   marks the previous one superseded, with both links retained.

Inline result payloads are bounded (`MAX_INLINE_CRITERION_EVALUATIONS`); larger
payloads stay in object storage.

## Benchmark validation

Benchmark cases are registered per ruleset version with a validation kind:

- `contract` — structural, deterministic and reproducibility validation. No
  clinical accuracy is claimed or reported.
- `scientific_accuracy` — only for cases carrying externally established expected
  classifications.

A run records case count, matches, mismatches, not-evaluated cases and per-case
comparisons. Runs whose cases are contract-only are reported as contract
validation, never as accuracy.

## API surface

Read and request:

- `GET /api/v1/interpretation-rulesets`, `GET /api/v1/interpretation-rulesets/{id}`
- `POST|GET /api/v1/classification-evaluations`
- `GET /api/v1/classification-evaluations/{id}`
- `GET /api/v1/classification-evaluations/{id}/interpretation`
- `GET /api/v1/classification-evaluations/variants/{variant_id}/history`

Platform administration (`platform.ruleset.administer`):

- `POST /api/v1/administration/interpretation-rulesets`
- `POST /api/v1/administration/interpretation-rulesets/{id}/state`
- `GET|POST /api/v1/administration/interpretation-rulesets/{id}/benchmark-cases`
- `GET|POST /api/v1/administration/interpretation-rulesets/{id}/benchmark-runs`

Workspace/project reads use the existing authorization and tenant model; tenancy
is always taken from the stored surface row, never from a request payload.
Ordinary users have no platform-level ruleset authority.

## Frontend

- `/admin/rulesets` — ruleset versions, lifecycle actions, declared criteria and
  combination rules, benchmark runs with their validation claim.
- Variant view — automated classification panel: suggestion, decision role,
  ruleset version, applied criteria, criterion evaluations, provenance digests and
  superseded history.

Neither surface computes anything scientific.
