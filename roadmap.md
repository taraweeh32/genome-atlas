# Package 8 — annotation resources & annotation ingestion

Vertical slice: resource registry → annotation profile → scientific execution
boundary → annotation ingestion → persistence/artifact → provenance → Package 7
field registry → API → UI/admin. No scientific algorithm is implemented; external
tools stay behind the existing scientific adapter.

- [ ] Vocabulary: annotation resource categories, run/result states, job kinds
- [ ] Permissions and platform role grants for annotation resource governance
- [ ] Scientific annotation contract (`app/scientific/annotation.py`)
- [ ] Domain: resource registry, profiles, runs, result versions, findings, field specs
- [ ] Domain: payload validation (schema, reference context, variant linkage, semantics)
- [ ] Persistence models + migration 0008 + repository ports + SQL repositories + doubles
- [ ] Use cases: resources, profiles, runs (scientific boundary), ingestion, fields
- [ ] Jobs: annotation execution + ingestion through the Package 5 durable job system
- [ ] Package 7 integration: annotation fields projected into the filter registry
- [ ] REST API under /api/v1 + admin endpoints
- [ ] Frontend: annotation status/provenance + platform admin resource management
- [ ] Focused Package 8 tests + lightweight regression check
- [ ] Documentation (`platform/docs/annotation.md`)

Carried forward (out of scope here): Package 2 migration hardening, mail transport,
duplicate TokenHasher/SystemClock instances, MFA enforcement, the Package 6
large-cohort sample-resolution issue, inherited lint debt. Later packages: evidence
evaluation, ACMG, interpretation, human review, reporting, scientific AI.
