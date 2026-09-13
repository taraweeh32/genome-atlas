# Package 3 report — identity, authentication, authorization, workspace / organization / project domain

Package 1 (foundation) and Package 2 (persistence baseline) are preserved
unchanged except where Package 3 legitimately extends them. The Package 2
migration-hardening item remains deliberately deferred and is documented in
section 24.

---

## 1. Scope delivered

Backend-authoritative identity and account lifecycle; password authentication and
server-side sessions; email verification and password recovery; personal
workspace provisioning; organization request/approval lifecycle; organization
memberships and invitations; roles and a single scoped authorization policy;
projects and project memberships with their own access relationship; the REST API
for all of the above; the real frontend flows; platform-administration
foundations; audit, activity and domain events; optimistic concurrency; security
and isolation tests; documentation.

Not in scope and not faked: datasets, files, analyses, jobs, variant data,
evidence, ACMG interpretation, reporting, notifications domain, search, MFA
enrolment, SSO. No scientific algorithm exists anywhere in this package.

## 2. Domain model

Framework-free entities and value objects: `User`, `Session`, `CredentialToken`,
`Workspace`, `Organization`, `OrganizationMembership`, `OrganizationInvitation`,
`Project`, `ProjectMembership`, plus identifier value objects, normalized email,
role enums and lifecycle enums. Entities contain no SQLAlchemy, HTTP or Redis
dependency; transitions are expressed as explicit lifecycle helpers that reject
invalid transitions.

## 3. Account lifecycle

`pending_verification → active → suspended | deactivated`, with retention state
(`active → soft_deleted → …`) tracked separately so an operational state is never
conflated with a deletion state. Administrative lifecycle changes require a
reason and are audited. Verification is required before sign-in.

## 4. Credentials

Argon2id hashing with a dedicated hasher exposing `hash`, `verify`,
`dummy_verify` (constant-work path for unknown accounts) and `algorithm`.
Credential material is isolated in `user_authentication_metadata` with failed
attempt counters and lockout timestamps. Password minimum length is policy-driven
(default 12).

## 5. Tokens

Verification, password-reset and invitation tokens are opaque high-entropy
values; only a peppered hash is persisted (`AUTH_TOKEN_PEPPER`). Tokens are
single-use with explicit states (`active / consumed / expired / invalidated`) and
expiries. In development the token is echoed in the response because no mail
transport is configured; no other environment returns it.

## 6. Sessions

Server-side session records referenced by an opaque HttpOnly, SameSite, Secure
cookie. Sliding idle expiry plus an independent absolute expiry; sliding never
exceeds the absolute limit. Per-account concurrent-session ceiling with oldest-
first revocation. Reauthentication window for sensitive operations. Sign-out
revokes the current session or every session for the account. IP is stored as a
hash and the user agent as a coarse summary.

## 7. CSRF and transport protections

Double-submit CSRF token: readable cookie plus `X-CSRF-Token` header, compared in
constant time, required for every unsafe method. Session cookie attributes are
environment-aware. The session is re-read from the store on every request, so a
revoked session is refused immediately.

## 8. Rate limiting

Fixed-window Redis limiter applied to authentication and registration per
identifier, surfaced as `RateLimitedError` with a retry hint. Limits are
configuration-driven, not hardcoded at call sites.

## 9. Authorization

One policy, deny-by-default. `ActorContext` is built solely from a verified
session and is fail-closed; it exposes platform, organization, workspace and
project capabilities and roles. `AuthorizationPolicy.decide(...)` returns a
decision whose `require()` raises `AuthenticationError` (no identity) or
`AuthorizationError` (identity, no permission). Authorization exists in exactly
one place; routes and use cases never re-derive it.

## 10. Tenant isolation

Workspace is the tenancy boundary; the personal/organization XOR is enforced by a
database check constraint. Cross-tenant reads raise *not found* rather than
*forbidden* so existence is not disclosed. Project queries are always scoped to a
workspace the caller reaches. Organization membership alone grants no project
access.

## 11. Workspaces

Every account receives exactly one personal workspace at verification; each
approved organization receives exactly one organization workspace. `GET
/workspaces` returns only workspaces the caller actually reaches.

## 12. Organizations

Creation is a request decided only by a platform administrator; approval
provisions the organization workspace and the requester's administrator
membership. Rejection requires a reason. Organization suspension and deactivation
are platform-scoped operations.

## 13. Memberships and invitations

Membership states `invited → active → left | removed` with actor and timestamp
attribution. Leaving or removal never deletes or transfers resources. Invitations
are hashed single-use tokens with expiry and explicit states; acceptance is
concurrency-safe.

## 14. Projects

Projects belong to exactly one workspace. Roles: `owner`, `manager`, `analyst`,
`reviewer`, `viewer`. `created_by` and `owner_user_id` are distinct. Project
membership is the access relationship; organization administrators reach projects
through an explicit, inert-membership enrichment in the policy rather than by
bypassing the check.

## 15. API surface

Versioned REST under `/api/v1`, documented in OpenAPI, thin handlers, dependency
injection, shared error responses:

- `POST /auth/register`, `/auth/verify-email`, `/auth/resend-verification`,
  `/auth/sign-in`, `/auth/sign-out`, `/auth/password-reset`,
  `/auth/password-reset/complete`, `/auth/password`
- `GET /me`
- `GET /workspaces`, `GET /workspaces/{id}`
- `POST|GET /organizations`, `GET|PATCH /organizations/{id}`,
  `POST|GET /organizations/{id}/invitations`,
  `DELETE /organizations/{id}/invitations/{invitation_id}`,
  `GET /organizations/{id}/members`,
  `PATCH|DELETE /organizations/{id}/members/{user_id}`,
  `GET /invitations/mine`, `POST /invitations/respond`
- `POST|GET /projects`, `GET|PATCH /projects/{id}`, `POST /projects/{id}/state`,
  `GET|POST /projects/{id}/members`,
  `PATCH|DELETE /projects/{id}/members/{user_id}`
- `GET /admin/users`, `POST /admin/users/{id}/state`,
  `POST /admin/users/{id}/platform-roles`, `GET /admin/organization-requests`,
  `POST /admin/organization-requests/{id}/decision`,
  `POST /admin/organizations/{id}/state`

## 16. Error contract

Unchanged envelope from Package 1:
`{"error": {"code", "message", "details?", "correlation_id"}}`. Authentication
failures are uniform to prevent account enumeration; concurrency conflicts map to
409; rate limiting to 429; hidden resources to 404.

## 17. Frontend

Public flows (`/login`, `/register`, `/verify`, `/recover`) and authenticated
surfaces (`/dashboard`, `/organizations`, `/projects`, `/admin`) are wired to the
real API. `SessionProvider` mirrors `GET /me` and holds no credential;
`useWorkspaceSync` loads the authoritative workspace list; `RequireSession` is a
presentation gate only. Every surface renders explicit loading, empty, error or
degraded states, refusals are stated rather than hidden, and no page contains
invented data. Navigation entries for unimplemented modules remain marked
unavailable.

## 18. Administration foundations

Platform administration lists accounts, changes account lifecycle with a
mandatory reason, grants and revokes platform roles, reviews organization
requests and changes organization state. Organization administration is a
separate authority and cannot reach any of these operations.

## 19. Audit, activity and events

Audit records carry actor, actor type, action, resource, reason, outcome and
correlation ID for every security-relevant and administrative operation.
Activity recording is a separate, non-authoritative signal. Domain events are
published in-process for later packages. Provenance and observability remain
separate systems.

## 20. Concurrency and integrity

Optimistic version checks in the unit of work raise `ConcurrencyConflictError`
on lost updates. Uniqueness (normalized email, organization slug, one personal
workspace per user, one workspace per organization, one membership per
user/organization) is enforced in the database, not only in services.

## 21. Configuration

`SecurityPolicySettings` covers password minimum length, failed-attempt ceiling,
idle and absolute session lifetimes, reauthentication window, concurrent-session
ceiling and the authentication/registration rate limits. `AUTH_TOKEN_PEPPER` is
required. All values are validated at startup; nothing security-relevant is
hardcoded at a call site.

## 22. Testing

179 backend tests and 21 frontend tests pass. Coverage includes registration and
verification, uniform authentication failures, lockout and rate limiting, session
idle/absolute expiry and sliding behaviour, CSRF, session revocation,
authorization matrices, tenant isolation and IDOR, workspace visibility,
organization approval, invitations, membership transitions, project isolation,
administrative authority separation, audit emission, concurrency conflicts, plus
frontend session-context, API-client CSRF, workspace-context and navigation tests.

Commands are in `docs/development-commands.md`.

## 23. Security posture and known limitations

Implemented: deny-by-default authorization, server-side sessions, Argon2id,
hashed tokens, CSRF, rate limiting, uniform failures, IDOR protection, audited
administration, secret-free client state.

Not yet implemented, by scope: MFA enrolment and challenge (the model is
MFA-ready — `mfa_enabled`, `mfa_satisfied` — but no factor is enrolled), SSO,
device management UI, per-organization security policy overrides, notification
delivery for invitations and verification (development returns tokens instead of
sending mail).

## 24. Deferred items

1. **Package 2 migration hardening** (still deferred, unchanged): the documented
   hardening of the Package 2 migration remains open and is intentionally not
   bundled into Package 3.
2. **Mail transport**: verification, reset and invitation delivery needs a real
   transport before any non-development environment.
3. **Duplicated infrastructure instances**: the container constructs separate
   `TokenHasher`/`SystemClock` instances for the token and session services; this
   is harmless but should be collapsed.

## 25. Conflicts found

None. No requirement was removed, no boundary simplified, no authorization moved
to the frontend, no scientific logic introduced, and no mock is presented as a
production implementation.
