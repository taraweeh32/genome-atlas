/**
 * Transport types for the identity, tenancy and administration endpoints.
 *
 * These mirror the REST contract exactly (snake_case field names) and describe
 * shapes only. Every permission listed in a `capabilities` array is an advisory
 * hint the backend produced for rendering; the backend re-authorizes each call,
 * so the frontend never treats a capability as a security decision.
 */

import type { EntityId, WorkspaceKind } from "./types";

export interface AccountResponse {
  readonly id: EntityId;
  readonly email: string;
  readonly display_name: string;
  readonly account_state: string;
  readonly email_verification_state: string;
  readonly personal_workspace_id: EntityId | null;
  readonly created_at: string;
}

export interface SessionSummaryResponse {
  readonly id: EntityId;
  readonly issued_at: string;
  readonly expires_at: string;
  readonly absolute_expires_at: string;
  readonly last_seen_at: string | null;
  readonly user_agent_summary: string | null;
}

export interface IdentityResponse {
  readonly account: AccountResponse;
  readonly session: SessionSummaryResponse;
  readonly platform_roles: readonly string[];
  readonly capabilities: readonly string[];
  readonly requires_reauthentication: boolean;
}

export interface AcknowledgementResponse {
  readonly accepted: boolean;
  readonly message: string;
  /** Present only in development, where no mail transport exists. */
  readonly development_only_token?: string | null;
}

export interface VerifyEmailResponse {
  readonly verified: boolean;
  readonly pending_invitation_count: number;
}

export interface PageMeta {
  readonly number: number;
  readonly size: number;
  readonly total: number;
}

export interface WorkspaceResponse {
  readonly id: EntityId;
  readonly kind: WorkspaceKind;
  readonly name: string;
  readonly organization_id: EntityId | null;
  readonly owner_user_id: EntityId | null;
  readonly capabilities: readonly string[];
}

export interface WorkspaceCollection {
  readonly items: readonly WorkspaceResponse[];
}

export interface OrganizationResponse {
  readonly id: EntityId;
  readonly slug: string;
  readonly name: string;
  readonly description: string | null;
  readonly state: string;
  readonly workspace_id: EntityId | null;
  readonly role: string | null;
  readonly capabilities: readonly string[];
  readonly requested_at: string | null;
  readonly approval_decided_at: string | null;
  readonly approval_decision_reason: string | null;
  readonly version: number;
}

export interface OrganizationCollection {
  readonly items: readonly OrganizationResponse[];
  readonly page: PageMeta;
}

export interface OrganizationReviewResponse {
  readonly id: EntityId;
  readonly slug: string;
  readonly name: string;
  readonly description: string | null;
  readonly state: string;
  readonly requested_by: EntityId | null;
  readonly requested_at: string | null;
}

export interface OrganizationReviewCollection {
  readonly items: readonly OrganizationReviewResponse[];
  readonly page: PageMeta;
}

export interface MembershipResponse {
  readonly id: EntityId;
  readonly organization_id: EntityId;
  readonly user_id: EntityId;
  readonly role: string;
  readonly state: string;
  readonly joined_at: string | null;
  readonly left_at: string | null;
}

export interface MembershipCollection {
  readonly items: readonly MembershipResponse[];
  readonly page: PageMeta;
}

export interface InvitationResponse {
  readonly id: EntityId;
  readonly organization_id: EntityId;
  readonly invited_email: string;
  readonly role: string;
  readonly state: string;
  readonly expires_at: string;
  readonly responded_at: string | null;
  readonly development_only_token?: string | null;
}

export interface InvitationCollection {
  readonly items: readonly InvitationResponse[];
  readonly page: PageMeta;
}

export interface MyInvitationResponse {
  readonly id: EntityId;
  readonly organization_id: EntityId;
  readonly role: string;
  readonly expires_at: string;
}

export interface MyInvitationCollection {
  readonly items: readonly MyInvitationResponse[];
}

export interface ProjectResponse {
  readonly id: EntityId;
  readonly workspace_id: EntityId;
  readonly name: string;
  readonly description: string | null;
  readonly state: string;
  readonly created_by: EntityId | null;
  readonly owner_user_id: EntityId | null;
  readonly role: string | null;
  readonly capabilities: readonly string[];
  readonly created_at: string;
  readonly version: number;
}

export interface ProjectCollection {
  readonly items: readonly ProjectResponse[];
  readonly page: PageMeta;
}

export interface ProjectMemberResponse {
  readonly id: EntityId;
  readonly project_id: EntityId;
  readonly user_id: EntityId;
  readonly role: string;
  readonly state: string;
  readonly joined_at: string | null;
}

export interface ProjectMemberCollection {
  readonly items: readonly ProjectMemberResponse[];
  readonly page: PageMeta;
}

export interface AccountAdministrationResponse {
  readonly id: EntityId;
  readonly email: string;
  readonly display_name: string;
  readonly account_state: string;
  readonly email_verification_state: string;
  readonly deletion_state: string;
  readonly last_activity_at: string | null;
  readonly created_at: string | null;
}

export interface AccountAdministrationCollection {
  readonly items: readonly AccountAdministrationResponse[];
  readonly page: PageMeta;
}
