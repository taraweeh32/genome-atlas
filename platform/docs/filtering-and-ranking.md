# Filtering and ranking

Package 7 adds two independent capabilities: **filtering** decides which variant
rows are members of a result page, and **ranking** decides in which order the
members are presented. They never merge. A ranking cannot reintroduce a row the
filter excluded, and a filter never produces a score. They are validated,
canonicalized, versioned, persisted, executed and audited separately.

## 1. Architecture

```text
browser  ──►  REST /api/v1 (filters, presets, rankings, variants/query)
                │
                ├─ authorization (Package 3 policy, scope + resource level)
                ├─ structural parsing        app/domain/query/expressions.py
                ├─ type-aware validation     app/domain/query/validation.py
                ├─ canonicalization + hash   app/domain/query/canonical.py
                ├─ ranking validation        app/domain/query/ranking.py
                │
                ▼
        application use cases              app/application/use_cases/query/
                │
                ├─ PostgreSQL: definitions, versions, presets, executions, views
                └─ analytical boundary (Package 6): DuckDB over Parquet
                       app/infrastructure/analytics/filter_compiler.py
                       app/infrastructure/analytics/query_engine.py
```

No second analytical store, job system, authorization model or variant model was
introduced. Deferred (large) queries run through the Package 5 durable job
system; analytical reads run through the Package 6 Parquet/DuckDB reader.

## 2. Filter expression schema

A filter is structured declarative data — never text, never code, never SQL.

```json
{
  "kind": "group",
  "operator": "and",
  "children": [
    {
      "kind": "condition",
      "field_id": "gene_symbol",
      "operator": "in",
      "values": ["CFTR", "ABCA4"],
      "value_type": "categorical",
      "negated": false,
      "field_definition_version": "1.0.0",
      "display_label": "Gene symbol",
      "metadata": {}
    },
    {
      "kind": "group",
      "operator": "or",
      "children": [
        { "kind": "condition", "field_id": "allele_frequency",
          "operator": "less_than", "values": [0.01] },
        { "kind": "condition", "field_id": "allele_frequency",
          "operator": "is_missing", "values": [] }
      ]
    }
  ]
}
```

Groups nest with `and`, `or` and `not`. A `not` group holds exactly one child.
Parsing is strict: unknown keys, unknown operators, unknown node kinds and
over-deep trees are refused with the failing path. Nothing is ever repaired.

## 3. Field dictionary

`app/domain/query/fields.py` publishes the dictionary (version
`FIELD_DICTIONARY_VERSION`). Each entry carries a stable id, label,
description, data type, supported operators, nullability, categorical values
where bounded, high-cardinality/searchable flags, sortable/filterable flags,
scientific category, source origin and the stored analytical column it reads.

Categories: variant identity, variant context, observation/sample, population,
annotation, clinical assertion. Data types: string, categorical, integer,
decimal, boolean, datetime, genomic position, identifier. No field is treated as
a string by default.

## 4. Operators

Operators are per data type; a field only ever publishes operators its type
supports. Equality/inequality, ordered comparison, `between` / `not_between` /
`within_range`, `in` / `not_in`, `contains` / `starts_with` / `ends_with`,
`is_empty` / `is_not_empty`, `is_true` / `is_false`, `before` / `after` / `on`,
and the presence tests `is_missing` / `is_present`.

## 5. Missing-value semantics

Missing, null, empty, unknown, zero and false are distinct facts and stay
distinct:

- `is_missing` compiles to a null test and nothing else.
- Every comparison carries an explicit `IS NOT NULL` guard, so a row that never
  reported a field is excluded because the data is missing — never because it was
  read as zero, false or an empty string.
- Negation compiles to `field IS NOT NULL AND NOT (...)`, so "not X" does not
  silently widen into "not X, or never reported".
- Ranking treats a missing input as unscored (`exclude`) unless a floor is
  explicitly configured; unscored rows sort last in both directions.

## 6. Validation and canonicalization

Validation checks field existence and context availability, operator support,
value type/format, value count and range, group structure, and resource limits
(depth, condition count, value-list size, text-match count, expression bytes,
value length). Every issue is reported at once with a code and a tree path.

Canonicalization produces a deterministic representation plus a SHA-256 hash:
lower-cased ids, deduplicated and sorted list values, ordered `and`/`or`
children, collapsed single-child wrappers. It performs no semantic rewriting —
no De Morgan, no NOT pushdown, no range merging — because a rewritten tree is no
longer the tree the user saved.

## 7. Analytical execution

`filter_compiler.py` is the only place a filter becomes SQL. Column names come
from the field dictionary by field id; every value travels as a bound parameter.
Predicates are pushed into `read_parquet`. Pages are bounded, ordering is
deterministic, and continuation uses a keyset cursor that carries a fingerprint
of the query so a cursor cannot be replayed against a different query. Reaching
the configured row ceiling is reported as a limit outcome, never as a page that
looks complete.

## 8. High-cardinality values

Fields such as gene symbol, transcript, sample and external identifier are
searched server side: a search term, a bounded page, an authorization check and
the result-set context. There is no unbounded distinct-value endpoint.

## 9. Saved filters, presets, rankings, saved views

One governed lifecycle serves all four configuration kinds: a mutable definition
(name, description, scope, owner, state, optimistic `version`) pointing at
append-only immutable content versions.

- Scopes: platform, organization, project, personal — a personal configuration is
  never globally visible, and an organization configuration never leaks to an
  unrelated organization.
- Editing content appends a new version; identical content is refused rather than
  recorded as a change that did not happen.
- A version referenced by an analysis execution is never rewritten.
- Concurrent edits are refused on a stale `expected_version`; the previous
  version survives and the caller must re-read and retry.
- Withdrawing a definition leaves its version history intact so a past result
  stays explainable.
- Saved views hold presentation state only (columns, order, pins, widths, sort,
  page size, default filter/ranking references). Sorting is not ranking.

## 10. Ranking

A ranking configuration names a registered method and version, a direction,
weighted components over explicitly supported stored fields, missing-value
behaviour and deterministic tie-breakers. Components are transparent numeric,
category-priority or presence contributions — there is no hidden pathogenicity
logic. Shipped methods declare `scientifically_validated = false`; a score is a
**prioritization score**, never a clinical conclusion.

Ordering is always primary score, then the configured tie-breakers, then a stable
identity key. Unscored rows sort last in both directions.

## 11. Analysis integration

At execution request time the analysis freezes a `query_binding` snapshot: the
filter definition and exact version, the preset and its version where used, the
ranking definition/preset and versions, the effective canonical expression and
hash, the field-dictionary version and the software version. Publishing a new
saved-filter or preset version afterwards cannot change a past execution's
resolution.

## 12. APIs

`/api/v1/filter-fields`, `/{field_id}`, `/{field_id}/values`;
`/api/v1/filters` and `/api/v1/filter-presets` with `/{id}`, `/{id}/versions`
and lifecycle transitions; `/api/v1/filters/validate`;
`/api/v1/variants/query` (bounded page, cursor, optional deferral);
`/api/v1/ranking-methods`; `/api/v1/rankings` and `/api/v1/ranking-presets`
with the same lifecycle shape; `/api/v1/saved-views`; and administration
endpoints for the field registry, the method registry and the safety limits.
Clients never send SQL and never receive raw queries.

## 13. Security

Authorization is server side at every step: scope grants for creating and
managing configurations, resource-level access for reading them, and result-set
authorization before any analytical read — including distinct-value search, so a
caller cannot mine values out of a dataset they cannot open. Personal and
organization boundaries are enforced in the repository query, not by hiding
controls in the browser. Frontend capabilities are a rendering hint only.

## 14. Auditing and provenance

Creation, metadata edits, new versions, lifecycle transitions and withdrawal are
audited with actor, scope, version number and canonical hash. Every executed
query writes an execution record: input result set and dataset version, filter
and preset versions, ranking and ranking-preset versions, field-dictionary
version, effective canonical expression, actor, timestamp, outcome, returned
count and pagination metadata.

## 15. Extension points

New fields are added to the dictionary with a bumped dictionary version. New
ranking methods are registered in the method registry with a version, required
fields, parameters and a deterministic implementation. New operators require a
type mapping in the operator table and a compilation in the filter compiler.

## 16. Scientific boundary

This package consumes stored scientific fields and derives none. It contains no
VEP invocation, no normalization or liftover, no HGVS generation, no consequence
prediction, no population-frequency calculation, no annotation generation, no
evidence evaluation, no ACMG classification and no clinical inference. Ranking is
transparent prioritization arithmetic over recorded values; scientific validity
of the consumed data belongs to the scientific layer.
