# Package 7 — variant filtering, saved filters, presets and ranking

Implementation order (per the package specification, section 60). All items below
are implemented and verified: backend 433 passed, frontend 54 passed.

- [x] Inspect Packages 1–6 abstractions (variant/result data layer, analytical boundary, authorization, jobs)
- [x] Vocabulary: filter/ranking enums and the shared definition lifecycle table
- [x] Permissions and role grants for filters, presets, rankings and saved views
- [x] Filter expression domain model (conditions, nested groups, operators, data types)
- [x] Filter field registry (dictionary + version + context availability)
- [x] Filter validation and canonicalization (+ canonical hash)
- [x] Ranking method registry and deterministic ranking framework
- [x] Saved filter / preset / ranking / saved view domain entities
- [x] Analytical filter execution (parameterized DuckDB compilation, predicate pushdown, keyset pagination)
- [x] Persistence models, migration 0007, repository ports, SQL repositories, in-memory doubles
- [x] Use cases: field dictionary, distinct-value search, variant query, saved filters, presets, rankings, saved views
- [x] Analysis configuration integration (frozen filter/ranking snapshot on execution)
- [x] Audit and provenance integration (filter/ranking execution records)
- [x] Deferred execution through the existing durable job system
- [x] REST API: filter fields, filters, presets, validation, variant query, rankings, saved views, admin
- [x] Frontend: filter builder, saved filters, presets, ranking controls, table columns/views
- [x] Admin surfaces (platform registry/presets/limits, organization presets)
- [x] Tests: unit, domain, API, analytical, security, concurrency, frontend
- [x] Documentation (`platform/docs/filtering-and-ranking.md`) and the Package 7 report

Deferred to later packages: annotation generation, evidence evaluation, the ACMG
engine, clinical interpretation, human review, reporting, scientific AI,
scientifically validated ranking models. Carried forward: Package 2 migration
hardening, mail transport, duplicate TokenHasher/SystemClock instances, inherited
lint debt, MFA enforcement, the Package 6 large-cohort sample-resolution issue.
