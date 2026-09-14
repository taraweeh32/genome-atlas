# Package 7 completion report — variant filtering, saved filters, presets and ranking

## 1. Package 7 Summary

Dynamic, server-side variant filtering and a separate deterministic ranking
framework are implemented end to end: filter expression domain model, type-aware
field dictionary, validation and canonicalization, parameterized DuckDB execution
over the existing Parquet boundary, keyset pagination, bounded high-cardinality
value search, saved filters, filter presets, saved rankings, ranking presets,
saved views, frozen filter/ranking snapshots on analysis executions, deferred
execution through the existing durable job system, REST APIs, frontend builder /
library / admin surfaces, audit and provenance records, tests and documentation.
Filtering and ranking remain architecturally separate at every layer.

## 2. Existing 1–6 Components Reused

Identity/session context and `ActorContext` (P3), authorization policy,
permissions, role grants and scope resolution (P3), workspace/organization/
project ownership and tenant isolation (P3–P4), dataset versions and result sets
(P4, P6), variant/result data model (P6), the DuckDB-over-Parquet analytical
reader boundary (P6), analysis definitions/configurations/executions (P5), the
durable job system with claiming, leases, retries and recovery (P5), the unit of
work, repository conventions, `ActivityRecorder` audit path and outbox (P1–P2),
the REST error taxonomy, pagination envelope and OpenAPI conventions (P1–P6), the
frontend shell, navigation, API client, `useApiResource` and UI primitives
(P3–P6). No component of Packages 1–6 was redesigned.

## 3. Files Added/Modified

Added (backend domain): `app/domain/query/__init__.py`, `operators.py`,
`expressions.py`, `canonical.py`, `fields.py`, `validation.py`, `ranking.py`,
`entities.py`, `pagination.py`.

Added (backend application): `app/application/use_cases/query/__init__.py`,
`dependencies.py`, `fields.py`, `definitions.py`, `execution.py`, `views.py`,
`deferred.py`, `analysis_binding.py`.

Added (backend infrastructure): `app/infrastructure/analytics/filter_compiler.py`,
`query_engine.py`; `app/infrastructure/persistence/models/queries.py`;
`app/infrastructure/persistence/repositories/queries.py`;
`app/workers/query_handlers.py`.

Added (transport): `app/api/v1/schemas/query.py`, `app/api/v1/query_mapping.py`,
`app/api/v1/routes/queries.py`.

Added (database): `platform/database/migrations/versions/0007_filtering_ranking.py`.

Added (frontend): `src/lib/query-types.ts`, `src/components/query/filter-builder.tsx`,
`ranking-controls.tsx`, `query.module.css`, `src/app/(app)/variant-query/{page,query-workbench}.tsx`,
`src/app/(app)/query-library/{page,library-view}.tsx`,
`src/app/(admin)/admin/query/{page,query-governance-view}.tsx`.

Added (tests): `platform/tests/query/{support,test_filter_execution,test_deferred_queries,test_filter_domain,test_ranking_domain,test_analysis_snapshot,test_configuration_lifecycle}.py`,
`platform/tests/api/test_query_endpoints.py`, frontend
`tests/query-client.test.ts`, `tests/filter-builder.test.tsx`.

Added (docs): `platform/docs/filtering-and-ranking.md`, this report.

Modified: `app/application/repositories.py` (query repository ports),
`app/application/container.py` (query services), `app/api/v1/router.py`,
`app/domain/authorization/permissions.py` and `roles.py` (query permissions and
grants), `app/domain/value_objects/enums.py` (query enums),
`app/infrastructure/persistence/unit_of_work.py`,
`app/infrastructure/persistence/models/__init__.py`,
`app/infrastructure/persistence/repositories/__init__.py`,
`app/application/use_cases/analysis/{configurations,executions}.py` (query
binding), `app/workers/dispatch.py`, `tests/support/memory.py` and
`tests/support/query_memory.py` (in-memory doubles), frontend
`src/lib/api-client.ts`, `src/components/shell/navigation.ts`,
`tests/navigation.test.ts`, `roadmap.md`.

## 4. Database Changes

Migration `0007_filtering_ranking` creates/extends: `filter_definitions`,
`filter_versions`, `filter_presets`, `filter_preset_versions`,
`ranking_definitions`, `ranking_versions`, `ranking_presets`,
`ranking_preset_versions`, `query_executions`, `ranking_executions`,
`saved_views`. Each definition table carries scope columns
(`workspace_id`, `project_id`, `organization_id`, `owner_user_id`) with foreign
keys, lifecycle state, `version` for optimistic concurrency,
`latest_version_number`, timestamps and audit linkage. Version tables are
append-only with `(definition_id, version_number)` uniqueness, canonical content,
canonical hash, field-dictionary version and a `referenced` flag. Indexes cover
scope lookups, owner lookups, state filtering and execution lookups by result
set and analysis execution.

## 5. Filter Domain Model

`FilterCondition` (field id, operator, values, value type, negated, field
definition version, display label, metadata) and `FilterGroup` (logical operator
plus children) form an immutable tree. `FilterNode` is the union. No node can
carry executable content.

## 6. Filter Expression Schema

Documented in `filtering-and-ranking.md` §2. Strict structural parsing:
unknown keys, unknown kinds, unknown operators, string expressions and
over-deep trees are refused with the failing tree path. A bare condition is
wrapped in a single-child group; nothing else is inferred.

## 7. Filter Field Registry

`FilterFieldRegistry` with `FIELD_DICTIONARY_VERSION` publishes ~40 definitions
across variant identity, variant context, observation/sample, population,
annotation and clinical assertion, each with data type, supported operators,
nullability, allowed values where bounded, high-cardinality/searchable and
sortable/filterable flags, origin, category and the stored column it reads.

## 8. Supported Operators

Type-aware sets per data type: equality, ordered comparison, `between`,
`not_between`, `within_range`, `in`, `not_in`, `contains`, `starts_with`,
`ends_with`, `is_empty`, `is_not_empty`, `is_true`, `is_false`, `before`,
`after`, `on`, `is_missing`, `is_present`. A field publishes only operators its
type supports (asserted by test).

## 9. Missing-Value Semantics

Missing, null, empty, unknown, zero and false remain distinct. Presence tests
compile to null tests only; every comparison carries an explicit null guard;
negation is `IS NOT NULL AND NOT (...)`; ranking leaves a missing input unscored
unless a floor is explicitly configured. Nothing is coerced.

## 10. Nested AND/OR

Groups nest arbitrarily within the configured depth limit with `and`, `or` and
`not`; a `not` group holds exactly one child. Nesting compiles to parenthesized
SQL preserving the authored structure.

## 11. Filter Validation

`validate_filter` checks field existence, context availability, operator support,
value type/format/length, value counts, range coherence, group structure and all
resource limits, reporting every issue at once with a stable code and path.
Nothing is repaired.

## 12. Filter Canonicalization

`canonicalize` + `canonical_hash` (SHA-256) give a deterministic representation:
lower-cased ids, deduplicated and sorted list values, ordered `and`/`or`
children, collapsed single-child wrappers, no semantic rewriting.

## 13. Analytical Query Architecture

`filter_compiler.py` translates a validated expression into a parameterized
predicate; `DuckDbQueryEngine` pushes it into `read_parquet`, applies bounded
page sizes, deterministic ordering and keyset continuation, and materializes
deferred results with `COPY … TO … (FORMAT PARQUET)`. No `SELECT *`, no client
SQL, no full-file loading, no second analytical store.

## 14. High-Cardinality Handling

`SearchFieldValues` performs authorized, context-scoped, bounded distinct-value
search with a search term and a hard result ceiling. There is no unbounded
distinct endpoint.

## 15. Variant Query API

`POST /api/v1/variants/query` accepts result set, filter, ranking, columns,
sort, page size and cursor; validates every component; returns a bounded page
with applied filter/ranking identity and versions, returned count, total count
only when computed (otherwise `null`, never substituted), next cursor,
deterministic ordering description and execution metadata. Expensive queries may
be deferred to a job.

## 16. Saved Filter Implementation

`SavedFilterService` over `filter_definitions` / `filter_versions`: create,
read (latest or a specific version), list within authorized scopes, rename,
append version, publish, archive, restore, withdraw — each audited.

## 17. Filter Versioning

Content versions are append-only and immutable, numbered strictly in sequence,
never reused. Identical content is refused as a version. A referenced version is
never rewritten. Earlier versions stay readable by number.

## 18. Filter Preset Implementation

`FilterPresetService` uses the same representation and lifecycle as saved
filters — a preset is not a second engine. Presets add applicable contexts and
publication state, and may be combined with a custom expression.

## 19. Preset Scope and Permissions

Platform presets require the platform-administer grant; organization presets
require the organization-manage grant for that organization; project and personal
presets require project membership or the owning workspace. Claiming a wider
scope is refused (tested).

## 20. Ranking Architecture

Ranking is a separate configuration, registry, validation path, persistence set
and execution record. It consumes stored fields and derives none. It cannot
change membership: ordering is applied to the filtered set only.

## 21. Ranking Method Registry

`RANKING_METHOD_REGISTRY` entries carry a stable id, name, description, version,
required fields, permitted parameters, applicable contexts, determinism flag,
implementation id and `scientifically_validated=false` for shipped methods.
Unknown methods, mismatched versions and unsupported parameters are refused.

## 22. Ranking Configuration

A configuration names the method and version, direction, weighted components
(numeric ascending/descending, category priority, presence) with scales,
missing-value behaviour and tie-breakers. Unknown component keys, unknown fields
and missing scales are refused.

## 23. Ranking Versioning

Identical to filters: mutable definition, append-only immutable versions,
optimistic concurrency, immutability once referenced by an execution.

## 24. Ranking Presets

`RankingPresetService` mirrors filter presets across platform, organization,
project and personal scopes, versioned and immutable once referenced.

## 25. Filter + Ranking Analysis Integration

`analysis_binding.py` validates the bound filter/ranking sections when a
configuration version is created and freezes a `query_binding` snapshot at
execution request time: definition ids, exact version ids and numbers, preset
identity and version, canonical expression and hash, ranking parameters and
tie-breakers, field-dictionary version and software version. Editing the saved
filter or ranking afterwards leaves the execution untouched (tested).

## 26. Reproducibility/Provenance

Every execution record links input result set and dataset version, filter and
preset versions, ranking and ranking-preset versions, field-dictionary version,
effective canonical expression and hash, actor, timestamp, outcome, returned
count and pagination metadata. Re-running creates a new execution; historical
ones are never mutated.

## 27. Audit Integration

Creation, metadata edits, version creation, publish/archive/restore/withdraw and
scope-sensitive refusals are audited through the existing `ActivityRecorder`
inside the same unit of work as the state change, with actor, scope, version
number and canonical hash.

## 28. Authorization/Tenant Isolation

All access decisions are server side, deny by default: scope grants for creation
and management, resource-level access for reads, result-set authorization before
any analytical read including value search. Personal and organization boundaries
are enforced in repository scope queries. IDOR attempts return 403/404 with no
content leak (tested).

## 29. Frontend Implementation

A real filter builder (nested AND/OR/NOT groups, type-aware operators, arity-
aware value inputs, inline validation issues, searchable high-cardinality
values), ranking controls (method, direction, weighted components, tie-breakers),
a variant-query workbench (result set, preset + custom filter, ranking, columns,
sorting separate from ranking, pagination, save as filter/ranking/view, defer as
job, "not reported" for nulls), a query library (filters, filter presets,
rankings, ranking presets with versions and lifecycle actions), saved views, and
explicit loading/error/empty states. Controls are capability-gated as a
rendering hint only. No demo or hardcoded scientific data.

## 30. Admin Implementation

Platform admin: field registry, ranking-method registry, platform presets,
global safety limits, activation/governance metadata. Organization admin:
organization filter and ranking presets and governance within platform limits.
Both are served by the same authoritative backend rules.

## 31. Performance/Resource Controls

Configurable limits on tree depth, condition count, value-list size, text-match
count, expression bytes and value length; bounded page sizes with a hard
maximum; a row ceiling for deferred materialization reported as a limit outcome;
cursor size limit and query fingerprinting; predicate pushdown to avoid reading
whole files.

## 32. Tests Implemented

Backend: `test_filter_domain.py` (32) structural parsing, type-aware validation,
limits, canonical form, combination, operator/type agreement;
`test_ranking_domain.py` (21) registry, scoring, determinism, ordering,
serialization; `test_filter_execution.py` (12) real Parquet/DuckDB filtering,
missing-value semantics, pagination, ordering, ranking separation;
`test_deferred_queries.py` (6) job routing, authorization, materialization, row
ceiling; `test_configuration_lifecycle.py` (16) scope claims, personal
isolation, concurrency, versioning, lifecycle, saved views;
`test_analysis_snapshot.py` (10) snapshot freezing and immutability;
`test_query_endpoints.py` (30) transport, authorization, IDOR, validation,
pagination, versions, value search. Frontend: `query-client.test.ts` (7),
`filter-builder.test.tsx` (8), plus the updated navigation test.

## 33. Test Results

Backend: **433 passed, 2 warnings** (pre-existing Starlette/anyio deprecation
warnings). Frontend: **54 passed**. Ruff lint clean on the package's files;
frontend typecheck and lint clean.

## 34. Security Verification

Verified by test: anonymous callers reach nothing; an outsider can neither list,
read, version nor delete another account's configuration; a platform scope
cannot be claimed without the grant; distinct-value search over an unauthorized
result set is refused; malformed, oversized and over-deep expressions are
refused; no client-supplied text reaches SQL (values are bound, columns come
from the dictionary); cursors are fingerprinted against their query.

## 35. Scientific-Boundary Verification

The scientific-boundary guard test covers the new modules. No VEP invocation, no
normalization or liftover, no HGVS generation, no consequence prediction, no
frequency calculation, no annotation generation, no evidence evaluation, no ACMG
logic, no clinical inference. Ranking is transparent arithmetic over recorded
values, labelled prioritization, with `scientifically_validated=false`.

## 36. Compatibility Verification

The full Package 1–6 suite passes unchanged inside the 433 total. No existing
schema was rewritten destructively, no authorization model duplicated, no second
job system or analytical store added, no variant/result model duplicated, and
existing API conventions and frontend shell patterns were followed.

## 37. Documentation

`platform/docs/filtering-and-ranking.md` covers architecture, expression schema,
field dictionary, operators, missing-value semantics, validation and
canonicalization, analytical execution, high-cardinality behaviour, saved
filters/presets/rankings/views, ranking architecture and registry, analysis
integration and reproducibility, APIs, security, auditing, extension points and
the scientific boundary.

## 38. Deferred Items

Annotation generation, evidence evaluation, the ACMG engine, clinical
interpretation, human review, reporting and scientific AI remain future
packages. Advanced, scientifically validated ranking models are out of scope
until separately validated and governed. Carried forward from earlier packages:
Package 2 migration hardening, mail transport, duplicate `TokenHasher`/
`SystemClock` instances, inherited lint debt, MFA enforcement, and the
large-cohort sample-resolution issue from Package 6 (not required for this
package's behaviour).

## 39. Known Limitations

Total counts are computed only when cheap; otherwise the response reports `null`
rather than an estimate. Stepwise per-condition counts are only shown when
actually computed. Query cancellation is honoured at page boundaries and through
job cancellation rather than mid-scan. Cross-node caching of field dictionaries
and preset metadata is context- and version-keyed but not yet warmed. The
in-memory doubles exercise repository semantics, not PostgreSQL constraint
enforcement, which the migration expresses.

## 40. DoD Verification

Server-side filtering with nested AND/OR/NOT, type-aware operators, preserved
missing-value semantics, bounded high-cardinality search, validated and
canonicalized definitions, versioned saved filters, scoped and immutable
presets, preset + custom combination, reproducible executions, an
architecturally separate registered and versioned ranking framework with
deterministic ordering, frozen analysis snapshots, reuse of the Parquet/DuckDB
boundary and the existing job system, server-side authorization and tenant
isolation, audit and provenance integration, functional frontend and admin
surfaces, REST contracts, and layered tests — all present and verified.

## 41. Final Status

**Package 7: COMPLETE.** No blocking architectural issue was found; no component
of Packages 1–6 was redesigned.

## 42. Next Package

Stopping here as instructed. Annotation, evidence, ACMG, interpretation and
reporting are not started.
