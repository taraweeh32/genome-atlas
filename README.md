# Genome Atlas

GENOMIC ANALYSIS & VARIANT INTERPRETATION PLATFORM

MASTER IMPLEMENTATION CONTEXT

VERSION 1.0

IMPORTANT:

This project already has a finalized and locked software architecture and requirements specification.

You are acting as the IMPLEMENTATION AGENT.

You are NOT the architecture authority.

You must implement the supplied architecture and requirements rather than redesigning them according to framework convenience, AI preference, or a simpler prototype approach.

==================================================

1. PRODUCT

==================================================

We are building a large-scale web-based genomic analysis and variant interpretation platform.

The platform supports:

- individual users

- personal workspaces

- organizations

- organization members

- projects

- genomic datasets

- files and dataset versions

- genomic analysis workflows

- asynchronous jobs

- configurable filtering

- configurable ranking/prioritization

- variant exploration

- annotation

- evidence

- ACMG/AMP interpretation workflows

- human scientific review

- adjudication

- reporting

- exports

- notifications

- search

- administration

- audit

- scientific provenance

- resource governance

- scalable scientific compute infrastructure

- future scientific methods and integrations

This is NOT merely:

- an ACMG calculator

- a VCF viewer

- a filtering table

- a reporting application

It is a modular genomic analysis platform.

==================================================

2. ARCHITECTURAL PRINCIPLE

==================================================

The application platform and the scientific compute subsystem are separate architectural boundaries.

Application:

Frontend

    ↓

API / Transport

    ↓

Application / Use Cases

    ↓

Domain

    ↓

Infrastructure

    ↓

Persistence / External Services

Scientific subsystem:

Application

    ↓

Scientific Integration Adapter / Contract

    ↓

Scientific Compute Environment

The scientific subsystem may run:

1. on the same machine in development/small deployments

2. on one separate scientific server

3. on multiple scientific servers

4. on a horizontally scaled scientific compute environment

The logical architecture must remain the same across these deployment modes.

==================================================

3. SCIENTIFIC BOUNDARY

==================================================

Scientific computation must remain outside the normal application-domain implementation.

Examples include:

- variant normalization

- reference genome processing

- VEP/consequence annotation

- population-frequency computation

- clinical database processing

- scientific evidence evaluation

- scientific pipelines

- ACMG/AMP rules execution

- gene/disease-specific scientific specifications

- scientific benchmarking

The application must communicate with these capabilities through explicit versioned contracts/adapters.

DO NOT implement hidden scientific logic inside:

- React components

- frontend utilities

- API controllers

- ordinary CRUD services

- database triggers

- arbitrary backend shortcuts

Development/test mocks may be used only at explicitly defined scientific integration boundaries.

Mocks must never masquerade as real scientific computation.

==================================================

4. CORE ARCHITECTURAL RULE

==================================================

The frontend is NOT authoritative.

The backend is authoritative for:

- authentication

- authorization

- tenant isolation

- permissions

- state transitions

- business rules

- data integrity

- workflow validity

- job lifecycle

- destructive operations

- configuration enforcement

- scientific integration requests

- audit generation

Never rely on frontend checks for security.

==================================================

5. WORKSPACE MODEL

==================================================

A user may exist without an organization.

Every user has a personal workspace.

A user may belong to multiple organizations.

Projects belong to exactly one workspace.

Resources inherit appropriate ownership/scope through the workspace/project model.

Personal resources are private by default.

Organization resources are collaborative according to explicit membership and permissions.

Organization membership does NOT automatically mean unrestricted access to every project/resource.

Creator and owner are separate concepts where required.

Leaving an organization must not silently delete or transfer organization resources.

==================================================

6. ADMINISTRATIVE MODEL

==================================================

There are distinct administrative levels.

Platform Administrator:

Controls platform-wide:

- users

- organizations

- organization approval

- platform configuration

- security policies

- storage

- retention

- compute infrastructure

- scientific resources

- global presets

- audit

- integrations

- resource governance

- incidents

- system health

Organization Administrator:

Controls only the organization's permitted:

- members

- projects

- organization resources

- organization configuration

- organization presets

- organization policies within platform limits

Organization administrators cannot:

- approve organizations

- manage platform infrastructure

- bypass platform security

- modify other organizations

- control global scientific resources

- bypass platform-wide governance

Scientific reviewer permissions are separate from administrative permissions.

==================================================

7. SECURITY

==================================================

Security is deny-by-default.

The implementation must support:

- secure authentication

- secure sessions

- strong password hashing

- account lifecycle

- email verification

- MFA-ready architecture

- mandatory stronger controls for privileged administration

- server-side authorization

- RBAC plus scoped permissions

- tenant isolation

- resource-level authorization

- IDOR protection

- API/UI permission parity

- secure file access

- secure object storage

- secure background jobs

- scientific-service authentication

- secret management

- auditability

- secure error handling

- rate limiting

- CSRF/session protections where applicable

- secure CORS/security headers

- sensitive genomic data protection

Never expose protected resources merely because a user knows an ID.

==================================================

8. DATA PRINCIPLES

==================================================

PostgreSQL is the authoritative transactional application database according to the locked technology specification.

Large genomic/result data must use the specified large-data/storage architecture rather than forcing everything into ordinary relational rows.

Dataset versions are immutable.

Scientific inputs and historical scientific outputs must remain reproducible.

Variant identity must explicitly account for:

- genome build

- chromosome/contig

- position

- reference allele

- alternate allele

- normalization/canonical representation

Source representation must be preserved.

Do not overwrite scientific source data merely to create a canonical representation.

Imported, retrieved, generated, automated, and human-evaluated information must remain distinguishable.

Missing, zero, false, unknown, and not-applicable values must not be silently conflated.

==================================================

9. JOB ARCHITECTURE

==================================================

Long-running operations must use durable asynchronous jobs where required.

Examples:

- genomic processing

- scientific execution

- imports

- exports

- large queries

- retention operations

- bulk administration

- scheduled operations

- notifications where appropriate

Jobs must support appropriate:

- lifecycle states

- secure execution context

- worker assignment

- concurrency-safe claiming

- heartbeats/leases

- stale-job recovery

- controlled retries

- cancellation

- idempotency

- progress

- error handling

- observability

- provenance

Application workers and scientific execution workers are architecturally distinct.

==================================================

10. SCIENTIFIC COMPUTE

==================================================

Scientific nodes are independently manageable resources.

The scheduler must be capability/resource aware.

Scheduling can consider:

- node health

- available worker capacity

- CPU

- memory

- storage

- capability

- scientific engine version

- reference/resource compatibility

- priority

- governance limits

Equivalent scientific nodes must use compatible/pinned scientific environments to preserve reproducibility.

==================================================

11. SCIENTIFIC PROVENANCE

==================================================

Scientific results must preserve lineage.

A scientific execution must be traceable to:

- input dataset version

- input files/artifacts

- analysis configuration

- filter configuration

- ranking configuration

- scientific pipeline

- scientific engine version

- reference genome

- annotation resources

- evidence resources

- ACMG/ruleset version

- execution environment

- node/environment identity where relevant

- execution timestamp

- relevant parameters

- produced artifacts/results

Never silently replace historical scientific context.

==================================================

12. ACMG / INTERPRETATION

==================================================

The application provides the workflow and integration boundary for ACMG/AMP interpretation.

The scientific ACMG engine remains independently implemented and validated.

Criterion evaluations must retain:

- criterion identifier

- strength

- evidence

- rationale

- source

- evaluator/method

- timestamp

- automated/human origin

- version/context

Human review must remain distinguishable from automated suggestions.

Human reviewers must be able to accept/reject/modify/add/remove/override according to permissions.

Conflicting evidence must not be silently discarded.

Finalized interpretations are versioned.

A later reclassification creates a new interpretation version rather than silently mutating historical interpretation.

==================================================

13. FILTERING & RANKING

==================================================

Filtering and ranking are separate concepts.

Filtering must support server-side large-data operations.

The platform must support:

- column-level filters

- type-aware operators

- categorical filtering

- numeric filtering

- string filtering

- boolean filtering

- date filtering where relevant

- high-cardinality search

- nested AND/OR logic

- saved filters

- presets

- project/personal/organization/platform scopes

Ranking must support:

- ranking methods

- ranking presets

- configurable weights where permitted

- versioning

- reproducibility

Filtering and ranking configurations must be preserved with analyses/executions where scientifically relevant.

==================================================

14. WORKFLOW STATE

==================================================

Backend-owned state machines are required.

Examples include:

- account

- organization

- project

- dataset

- analysis

- job

- interpretation

- report

- retention/deletion

The frontend may request transitions but must never independently define authoritative state.

Invalid transitions must be rejected server-side.

Important state changes must be auditable.

Operational state, review state, and deletion/retention state must remain conceptually separate.

==================================================

15. AUDIT VS PROVENANCE VS OBSERVABILITY

==================================================

These are different systems.

Audit:

Who performed what operation and when.

Scientific provenance:

How scientific information/result was produced.

Operational observability:

How the system behaved technically.

Activity:

User-facing collaboration/activity information.

Do not collapse these into one generic logging mechanism.

==================================================

16. RETENTION & DELETION

==================================================

Deletion is lifecycle-controlled.

Typical lifecycle:

active

    ↓

soft deleted

    ↓

retention/recovery period

    ↓

permanent deletion

Deletion must be:

- authorization controlled

- dependency aware

- auditable

- recoverable where applicable

- safe for scientific lineage

- safe for immutable historical records

- separate from backup lifecycle

Do not permanently delete data merely because a user presses a normal delete button.

==================================================

17. REPORTING

==================================================

Interactive results, result sets, interpretations, reports, and exports are distinct concepts.

Reports must preserve relevant versions and provenance.

Changing a later interpretation must not silently mutate an already finalized historical report.

Large exports should be asynchronous where appropriate.

Exports require explicit authorization.

==================================================

18. FRONTEND

==================================================

The frontend must be:

- modular

- accessible

- responsive

- permission-aware

- scientific-workflow oriented

- capable of dense data presentation

- capable of large variant-table interaction

- explicit about loading/error/degraded states

- safe for destructive actions

- optimized for large datasets

Do not build fake scientific dashboards using hardcoded data and call them complete.

Development fixtures may be used where explicitly appropriate, but they must be clearly separated from production data flows.

==================================================

19. ADMINISTRATION

==================================================

The administration system is a full control plane.

It must eventually cover:

- users

- organizations

- memberships

- roles

- projects

- datasets

- files

- storage

- jobs

- compute nodes

- workers

- scientific resources

- presets

- review workflows

- reports

- notifications

- automation

- system configuration

- APIs

- service accounts

- audit

- security

- backup/recovery

- resource governance

- monitoring

- incidents

- change control

Administrative functionality must use the same authoritative backend domain/security rules as the rest of the application.

==================================================

20. OBSERVABILITY

==================================================

Use structured operational observability.

Important correlation should be possible across:

request

→ API operation

→ job

→ worker

→ scientific execution

→ artifact/result

Do not place sensitive genomic contents unnecessarily into logs or telemetry.

==================================================

21. TESTING

==================================================

Testing is part of implementation, not an afterthought.

The system must eventually support:

- unit tests

- component tests

- domain tests

- API tests

- integration tests

- E2E tests

- authorization tests

- tenant-isolation tests

- data-integrity tests

- concurrency tests

- job tests

- failure/recovery tests

- performance tests

- accessibility tests

- scientific integration tests

- regression tests

Scientific validity itself must be independently benchmarked and validated.

==================================================

22. DEVELOPMENT METHOD

==================================================

We will implement this project in staged packages.

You will receive:

PACKAGE 0

Master Context

PACKAGE 1

Foundation + Repository + Application Shell

PACKAGE 2

Database + Domain + Persistence

PACKAGE 3

Authentication + Authorization + Tenancy

PACKAGE 4

Organizations + Workspaces + Projects

PACKAGE 5

Datasets + Files + Import + Validation

PACKAGE 6

Jobs + Workers + Scheduling

PACKAGE 7

Scientific Integration Boundary

PACKAGE 8

Analysis Configuration + Execution

PACKAGE 9

Results + Variants

PACKAGE 10

Filtering + Ranking + Saved Views

PACKAGE 11

Annotations + Evidence

PACKAGE 12

ACMG Interpretation + Human Review

PACKAGE 13

Reports + Exports

PACKAGE 14

Notifications + Search + Activity

PACKAGE 15

Administration

PACKAGE 16

Observability + Governance + Lifecycle

PACKAGE 17

Testing + Security + Performance

PACKAGE 18

Full Integration + Production Readiness

Only implement the current package when instructed.

However, preserve compatibility with the complete architecture.

==================================================

23. ABSOLUTE IMPLEMENTATION RULES

==================================================

DO NOT:

- redesign the architecture

- replace locked technologies

- remove requirements

- simplify tenant boundaries

- bypass authorization

- move security checks into frontend-only logic

- implement scientific algorithms inside ordinary application code

- use hardcoded fake production data

- create fake completion states

- silently omit difficult features

- silently change data semantics

- silently mutate historical scientific results

- replace durable jobs with browser-only operations

- create uncontrolled arbitrary command execution

- claim mocks are production scientific implementations

If a requirement appears technically difficult or conflicts with another requirement:

STOP and clearly identify the conflict.

Do not silently invent a different architecture.

==================================================

24. IMPLEMENTATION QUALITY

==================================================

Generated code must be:

- modular

- maintainable

- typed where supported by the locked stack

- testable

- explicit

- reviewable

- domain-oriented

- appropriately documented

Avoid giant components, giant services, hidden magic, duplicated authorization, and unnecessary abstraction.

==================================================

25. COMPLETENESS RULE

==================================================

A feature is not considered complete merely because:

- a page exists

- a button exists

- a modal exists

- fake data appears

- a database table exists

A feature is complete only when all applicable layers exist:

UI

→ API

→ authorization

→ application/domain logic

→ persistence

→ job/integration if required

→ audit/provenance where required

→ tests

==================================================

26. CURRENT INSTRUCTION

==================================================

For now, DO NOT implement the entire platform.

First acknowledge this Master Implementation Context and prepare to receive PACKAGE 1.

Do not redesign the architecture.

Do not substitute technologies.

Do not generate the complete application yet.

Wait for PACKAGE 1.

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/e4ca559a-f6e7-4bdd-9ef7-18e13c3d1a81).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```
