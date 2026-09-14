# Packages 9–17 — remaining implementation program

Order is fixed: 9 → 10 → 11 → 12 → 13 → 14 → 15 → 16 → 17 → final integration.
Reuse the existing job system, scientific boundary, authorization, provenance,
variant/result model and analytical storage. No second anything.

- [x] **Package 9 — evidence resources & evidence model.** Source registry with
      versions and lifecycle, evidence records with origin/provenance/versioning,
      validated idempotent deliveries with findings, conflict preservation,
      tenant isolation, migration 0009, 11 endpoints, admin + variant UI,
      21 focused tests, docs.
- [x] **Package 10 — ACMG/AMP rules engine & classification framework.**
      Independently identifiable scientific component; versioned rulesets and
      criteria; structured interpretation requests through the existing adapter;
      automated suggestion ≠ human decision; benchmark-corpus interface.
      Migration 0010, admin ruleset governance UI, variant classification panel.
- [x] **Package 11 — interpretation, human review & adjudication.** Migration
      0011, versioned interpretations pinning ruleset/criteria/evidence by
      reference, append-only reviewer decisions, disagreement escalation and
      adjudication, immutable finalization with reclassification successors,
      optimistic concurrency, `/interpretations` review workspace, 20 focused
      tests, `docs/review-and-adjudication.md`.
- [ ] **Package 12 — reporting, report versions & export.**
- [ ] **Package 13 — notifications, events & automation.**
- [ ] **Package 14 — search, discovery & cross-resource navigation.**
- [ ] **Package 15 — advanced administration & governance** (includes MFA
      enforcement for platform admins — required, not deferred).
- [ ] **Package 16 — scientific validation, benchmarking & reproducibility.**
- [ ] **Package 17 — final production hardening & system integration**, then the
      final cross-package workflow verification.

## Deferred, to be handled in Package 17 unless stated otherwise

- Package 2 migration hardening
- Mail transport (interface may stay adapter-based)
- Duplicate TokenHasher / SystemClock cleanup
- Package 6 large-cohort sample resolution — must be fixed before claiming
  production-scale cohort ingestion readiness
- Inherited frontend lint/plugin conflict
- Artifact-backed annotation and evidence batches are located but not parsed
