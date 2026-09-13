/**
 * Types mirroring the versioned REST API contract.
 *
 * These describe transport shapes only. Domain rules, permissions and state
 * transitions are owned by the backend; the frontend never re-implements them.
 */

/** Opaque, prefixed, backend-generated identifier (e.g. `wsp_...`). */
export type EntityId = string;

export type WorkspaceKind = "personal" | "organization";

export interface WorkspaceRef {
  readonly id: EntityId;
  readonly kind: WorkspaceKind;
  readonly name: string;
  /** Present only for organization workspaces. */
  readonly organizationId?: EntityId;
}

export interface ProjectRef {
  readonly id: EntityId;
  readonly workspaceId: EntityId;
  readonly name: string;
}

export interface ApiErrorBody {
  readonly error: {
    readonly code: string;
    readonly message: string;
    readonly details?: Record<string, unknown>;
    readonly correlation_id?: string;
  };
}

export interface HealthResponse {
  readonly status: string;
  readonly environment: string;
  readonly version: string;
  readonly checked_at: string;
}

export type DependencyStatus = "up" | "degraded" | "down" | "not_configured";

export interface DependencyStatusResponse {
  readonly name: string;
  readonly status: DependencyStatus;
  readonly required: boolean;
  readonly latency_ms?: number | null;
  readonly detail?: string | null;
}

export interface ReadinessResponse {
  readonly ready: boolean;
  readonly checked_at: string;
  readonly dependencies: readonly DependencyStatusResponse[];
}

export interface MetaResponse {
  readonly name: string;
  readonly api_version: string;
  readonly environment: string;
  readonly version: string;
}
