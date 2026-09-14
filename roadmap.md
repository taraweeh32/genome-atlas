# Package 7 — variant filtering, saved filters, presets and ranking

Implementation order (per the package specification, section 60).

- [x] Inspect Packages 1–6 abstractions (variant/result data layer, analytical boundary, authorization, jobs)
- [x] Vocabulary: filter/ranking enums (`QueryScope`, `QueryDefinitionState`, `QueryExecutionOutcome`) and the shared definition lifecycle table
- [ ] Permissions and role grants for filters, presets, rankings and saved views
- [x] Filter expression domain model (conditions, nested groups, operators, data types)
- [x] Filter field registry (dictionary + version + context availability)
- [x] Filter validation and canonicalization (+ canonical hash)
- [x] Ranking method registry and deterministic ranking framework
- [x] Saved filter / preset / ranking / saved view domain entities
- [ ] Analytical filter execution (parameterized DuckDB compilation, predicate pushdown, keyset pagination)
- [ ] Persistence models, migration 0007, repository ports, SQL repositories, in-memory doubles
- [ ] Use cases: field dictionary, distinct-value search, variant query, saved filters, presets, rankings
- [ ] Analysis configuration integration (frozen filter/ranking snapshot on execution)
- [x] Audit and provenance integration (filter/ranking execution records)
- [x] Deferred execution through the existing durable job system
- [ ] REST API: filter fields, filters, presets, validation, variant query, rankings, admin
- [ ] Frontend: filter builder, saved filters, presets, ranking controls, table columns/views
- [ ] Admin surfaces (platform registry/presets/limits, organization presets)
- [ ] Tests: unit, domain, API, analytical, security, concurrency, frontend
- [ ] Documentation (`platform/docs/filtering-and-ranking.md`) and Package 7 report
