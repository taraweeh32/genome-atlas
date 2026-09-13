# Identity, authentication, authorization and tenancy

This document describes the model implemented in Package 3. It is normative for
every later package: no module may reimplement, weaken or bypass what is
described here.

## 1. Authority

The backend is the sole authority for identity, sessions, permissions, tenancy
and state transitions. The frontend renders what the backend reports and
*requests* transitions. `capabilities` arrays returned by the API are advisory
rendering hints; hiding a control is never a security control, because every
request is authorized again server-side.

## 2. Accounts

An account exists independently of any organization.

- Lifecycle: `pending_verification → active → suspended | deactivated`, with a
  separate retention/deletion state (`active → soft_deleted → …`). Operational
  state and deletion state are never conflated.
- Email is stored twice: as entered and case-folded (`email_normalized`), which
  is the uniqueness authority.
- Passwords are hashed with Argon2id. Credential material lives in
  `user_authentication_metadata`, not on the account row, so ordinary account
  reads never touch secrets.
- Registration answers uniformly whether or not the address exists: registration
  never discloses account existence.
- Email verification and password reset use single-use opaque tokens; only a
  peppered hash is persisted. In development the token is returned in the
  response body because no mail transport is configured — it is never returned in
  any other environment.
- Completing a password reset revokes every session for that account.

## 3. Sessions

Sessions are server-side records referenced by an opaque, HttpOnly, SameSite
cookie (`gp_session`). The browser never holds a bearer token, and no
authorization data is stored client-side.

- Two independent expiries: sliding idle expiry (default 60 minutes) and a fixed
  absolute expiry (default 12 hours). Sliding never extends past the absolute
  limit.
- A per-account ceiling on concurrent sessions; the oldest is revoked when the
  ceiling is exceeded.
- CSRF: a double-submit token in a readable cookie (`gp_csrf`) that must be
  echoed in `X-CSRF-Token` for every state-changing request. Comparison is
  constant-time.
- Sensitive operations require recent reauthentication (default window 15
  minutes); `requires_reauthentication` on `GET /me` reports this.
- Client attributes (IP, user agent) are stored as a hash and a coarse summary,
  never verbatim.
- Authentication and registration are rate limited per identifier with a
  fixed-window limiter in Redis.

## 4. Workspaces

A workspace is the tenancy boundary and is either *personal* or *organization*,
enforced by a database check constraint:

- every account has exactly one personal workspace, provisioned by the backend;
- an organization workspace is provisioned when the organization is approved;
- a project belongs to exactly one workspace;
- personal workspace resources are private by default.

`GET /workspaces` returns the caller's personal workspace plus organization
workspaces their active memberships reach. The frontend never assembles this list.

## 5. Organizations

Creating an organization is a *request*. Only a platform administrator decides
it (`requested → active` or `rejected`); an organization administrator cannot
approve organizations, alter other organizations, manage platform
infrastructure or control global scientific resources.

Membership is explicit and has its own state (`invited → active → left | removed`).
Leaving or being removed records timestamps and actors; it never deletes or
transfers resources. Invitations are single-use hashed tokens with an expiry.

**Organization membership never implies project access.**

## 6. Projects

Project access is a separate relationship (`project_memberships`) with its own
roles: `owner`, `manager`, `analyst`, `reviewer`, `viewer`. Creator and owner are
distinct fields and may differ.

## 7. Authorization

Authorization is deny-by-default and evaluated by a single policy:

```
AuthorizationPolicy.decide(actor, permission, *, organization_id, workspace_id, project_id)
    -> AuthorizationDecision   # .require() raises AuthenticationError or AuthorizationError
```

- `ActorContext` is built per request from the verified session; it is fail-closed
  and carries platform roles, organization roles, project roles and the scoped
  permission set. Nothing else may construct an authenticated actor.
- Permissions are scoped strings (platform, organization, workspace, project).
  A permission is only satisfied within the scope it was granted.
- Reading a resource the caller may not see raises *not found*, not *forbidden*,
  so existence is not disclosed (IDOR protection). Deliberate exception:
  administrative endpoints answer *forbidden*, because the resource class is
  public knowledge.
- Scientific reviewer permissions are separate from administrative permissions.

## 8. Concurrency

Mutable rows carry a `version` column. Updates go through the unit of work,
which performs an optimistic version check and raises
`ConcurrencyConflictError` on a lost update (HTTP 409). Invitation acceptance,
membership changes and lifecycle transitions are therefore safe under
concurrent callers.

## 9. Audit, activity and events

Three separate systems, deliberately not collapsed:

- **audit** — who did what to which resource, with reason and outcome, for
  security-relevant and administrative operations;
- **activity** — non-authoritative recent-activity signal;
- **domain events** — in-process notifications that later packages subscribe to.

Provenance (scientific lineage) and observability (logs, metrics, traces) are
again separate and are not written by this package.

## 10. Frontend surfaces

| Route | Purpose |
| --- | --- |
| `/login`, `/register`, `/verify`, `/recover` | public identity flows |
| `/dashboard` | authenticated overview, real platform status and workspace context |
| `/organizations` | reachable organizations, invitations, organization requests |
| `/projects` | projects in the active workspace, project creation |
| `/admin` | platform administration: accounts, organization requests |

`RequireSession` avoids rendering an authenticated shell to an anonymous
visitor and preserves the blocked path. It grants nothing.

## 11. Error contract

Every failure is the structured envelope
`{"error": {"code", "message", "details?", "correlation_id"}}`. Authentication
failures are uniform ("the credentials were not accepted") regardless of cause,
so accounts cannot be enumerated. Internal details, stack traces and hashes are
never returned.
