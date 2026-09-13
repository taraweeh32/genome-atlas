/**
 * API client for the versioned REST backend.
 *
 * The client is the *only* way the frontend obtains state. It:
 * - always targets `/api/v1`;
 * - sends and surfaces a correlation ID so a UI failure can be traced to logs;
 * - decodes the backend's structured error envelope into a typed error;
 * - never assumes anything about permissions: authorization answers come from
 *   the backend response, not from client-side checks.
 */

import { apiUrl, loadFrontendConfig, type FrontendConfig } from "./config";
import { CSRF_HEADER_NAME, readCsrfToken } from "./csrf";
import type {
  AccountAdministrationCollection,
  AccountAdministrationResponse,
  AcknowledgementResponse,
  IdentityResponse,
  InvitationCollection,
  InvitationResponse,
  MembershipCollection,
  MyInvitationCollection,
  OrganizationCollection,
  OrganizationResponse,
  OrganizationReviewCollection,
  ProjectCollection,
  ProjectMemberCollection,
  ProjectMemberResponse,
  ProjectResponse,
  VerifyEmailResponse,
  WorkspaceCollection,
  WorkspaceResponse,
} from "./identity-types";
import type {
  AnalysisCollection,
  AnalysisResponse,
  ConfigurationCollection,
  ConfigurationResponse,
  ExecutionCollection,
  ExecutionProvenanceResponse,
  ExecutionResponse,
  JobCollection,
  JobResponse,
  ScheduleCollection,
  ScheduleResponse,
} from "./analysis-types";
import type {
  ColumnMappingDecision,
  DatasetCollection,
  DatasetResponse,
  DatasetVersionCollection,
  DatasetVersionResponse,
  DownloadGrantResponse,
  ImportSessionCollection,
  ImportSessionResponse,
  UploadSessionResponse,
  UploadTicketResponse,
  ValidationRunCollection,
  ValidationRunResponse,
} from "./data-types";
import type {
  ApiErrorBody,
  HealthResponse,
  MetaResponse,
  ReadinessResponse,
} from "./types";

export const CORRELATION_ID_HEADER = "X-Correlation-ID";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details?: Record<string, unknown>,
    readonly correlationId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /**
   * Whether retrying the same request can plausibly succeed. Transport failures
   * (status 0), server failures and throttling are retryable; a rejected or
   * missing resource is not.
   */
  get isRetryable(): boolean {
    return this.status === 0 || this.status >= 500 || this.status === 429;
  }
}

const UNSAFE_METHODS = new Set(["POST", "PATCH", "PUT", "DELETE"]);

export interface RequestOptions {
  readonly method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  readonly body?: unknown;
  readonly correlationId?: string;
  readonly signal?: AbortSignal;
}

export interface ApiClientOptions {
  readonly config?: FrontendConfig;
  readonly fetchImpl?: typeof fetch;
  readonly newCorrelationId?: () => string;
  /** Overridable so tests do not depend on document.cookie. */
  readonly csrfTokenReader?: () => string | null;
}

function defaultCorrelationId(): string {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : Math.random().toString(16).slice(2);
  return `web-${random}`;
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof (value as ApiErrorBody).error?.code === "string"
  );
}

export class ApiClient {
  private readonly config: FrontendConfig;
  private readonly fetchImpl: typeof fetch;
  private readonly newCorrelationId: () => string;
  private readonly readCsrfToken: () => string | null;

  constructor(options: ApiClientOptions = {}) {
    this.config = options.config ?? loadFrontendConfig();
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
    this.newCorrelationId = options.newCorrelationId ?? defaultCorrelationId;
    this.readCsrfToken = options.csrfTokenReader ?? (() => readCsrfToken());
  }

  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const correlationId = options.correlationId ?? this.newCorrelationId();
    const headers: Record<string, string> = {
      Accept: "application/json",
      [CORRELATION_ID_HEADER]: correlationId,
    };
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    const method = options.method ?? "GET";
    if (UNSAFE_METHODS.has(method)) {
      // Double-submit token. Absent when there is no session; the backend then
      // refuses the request, which is the correct outcome.
      const csrf = this.readCsrfToken();
      if (csrf) {
        headers[CSRF_HEADER_NAME] = csrf;
      }
    }

    let response: Response;
    try {
      response = await this.fetchImpl(apiUrl(this.config, path), {
        method,
        headers,
        credentials: "include",
        signal: options.signal,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
      });
    } catch (cause) {
      throw new ApiError(
        0,
        "network_error",
        "The platform API could not be reached.",
        undefined,
        correlationId,
      );
    }

    const payload = response.status === 204 ? null : await this.parseJson(response);

    if (!response.ok) {
      if (isErrorBody(payload)) {
        throw new ApiError(
          response.status,
          payload.error.code,
          payload.error.message,
          payload.error.details,
          payload.error.correlation_id ?? correlationId,
        );
      }
      throw new ApiError(
        response.status,
        "unexpected_error",
        "The platform API returned an unexpected response.",
        undefined,
        response.headers.get(CORRELATION_ID_HEADER) ?? correlationId,
      );
    }

    return payload as T;
  }

  private async parseJson(response: Response): Promise<unknown> {
    try {
      return await response.json();
    } catch {
      return null;
    }
  }

  // -- system endpoints available in Package 1 -----------------------------

  health(options?: RequestOptions): Promise<HealthResponse> {
    return this.request<HealthResponse>("/health", options);
  }

  readiness(options?: RequestOptions): Promise<ReadinessResponse> {
    return this.request<ReadinessResponse>("/ready", options);
  }

  meta(options?: RequestOptions): Promise<MetaResponse> {
    return this.request<MetaResponse>("/meta", options);
  }

  // -- identity ------------------------------------------------------------

  register(body: {
    email: string;
    password: string;
    display_name: string;
  }): Promise<AcknowledgementResponse> {
    return this.request<AcknowledgementResponse>("/auth/register", { method: "POST", body });
  }

  verifyEmail(token: string): Promise<VerifyEmailResponse> {
    return this.request<VerifyEmailResponse>("/auth/verify-email", {
      method: "POST",
      body: { token },
    });
  }

  resendVerification(email: string): Promise<AcknowledgementResponse> {
    return this.request<AcknowledgementResponse>("/auth/resend-verification", {
      method: "POST",
      body: { email },
    });
  }

  signIn(email: string, password: string): Promise<IdentityResponse> {
    return this.request<IdentityResponse>("/auth/sign-in", {
      method: "POST",
      body: { email, password },
    });
  }

  signOut(allSessions = false): Promise<null> {
    return this.request<null>("/auth/sign-out", {
      method: "POST",
      body: { all_sessions: allSessions },
    });
  }

  requestPasswordReset(email: string): Promise<AcknowledgementResponse> {
    return this.request<AcknowledgementResponse>("/auth/password-reset", {
      method: "POST",
      body: { email },
    });
  }

  completePasswordReset(token: string, newPassword: string): Promise<null> {
    return this.request<null>("/auth/password-reset/complete", {
      method: "POST",
      body: { token, new_password: newPassword },
    });
  }

  changePassword(currentPassword: string, newPassword: string): Promise<null> {
    return this.request<null>("/auth/password", {
      method: "POST",
      body: { current_password: currentPassword, new_password: newPassword },
    });
  }

  identity(options?: RequestOptions): Promise<IdentityResponse> {
    return this.request<IdentityResponse>("/me", options);
  }

  // -- tenancy -------------------------------------------------------------

  workspaces(options?: RequestOptions): Promise<WorkspaceCollection> {
    return this.request<WorkspaceCollection>("/workspaces", options);
  }

  workspace(id: string): Promise<WorkspaceResponse> {
    return this.request<WorkspaceResponse>(`/workspaces/${encodeURIComponent(id)}`);
  }

  organizations(options?: RequestOptions): Promise<OrganizationCollection> {
    return this.request<OrganizationCollection>("/organizations", options);
  }

  requestOrganization(body: {
    name: string;
    slug: string;
    description?: string | null;
  }): Promise<OrganizationResponse> {
    return this.request<OrganizationResponse>("/organizations", { method: "POST", body });
  }

  organizationMembers(organizationId: string): Promise<MembershipCollection> {
    return this.request<MembershipCollection>(
      `/organizations/${encodeURIComponent(organizationId)}/members`,
    );
  }

  invitations(organizationId: string): Promise<InvitationCollection> {
    return this.request<InvitationCollection>(
      `/organizations/${encodeURIComponent(organizationId)}/invitations`,
    );
  }

  invite(
    organizationId: string,
    body: { email: string; role: string },
  ): Promise<InvitationResponse> {
    return this.request<InvitationResponse>(
      `/organizations/${encodeURIComponent(organizationId)}/invitations`,
      { method: "POST", body },
    );
  }

  myInvitations(): Promise<MyInvitationCollection> {
    return this.request<MyInvitationCollection>("/invitations/mine");
  }

  respondToInvitation(token: string, accept: boolean): Promise<null> {
    return this.request<null>("/invitations/respond", {
      method: "POST",
      body: { token, accept },
    });
  }

  projects(params?: { workspace_id?: string }): Promise<ProjectCollection> {
    const query = params?.workspace_id
      ? `?workspace_id=${encodeURIComponent(params.workspace_id)}`
      : "";
    return this.request<ProjectCollection>(`/projects${query}`);
  }

  createProject(body: {
    workspace_id: string;
    name: string;
    description?: string | null;
  }): Promise<ProjectResponse> {
    return this.request<ProjectResponse>("/projects", { method: "POST", body });
  }

  projectMembers(projectId: string): Promise<ProjectMemberCollection> {
    return this.request<ProjectMemberCollection>(
      `/projects/${encodeURIComponent(projectId)}/members`,
    );
  }

  addProjectMember(
    projectId: string,
    body: { user_id: string; role: string },
  ): Promise<ProjectMemberResponse> {
    return this.request<ProjectMemberResponse>(
      `/projects/${encodeURIComponent(projectId)}/members`,
      { method: "POST", body },
    );
  }

  // -- administration ------------------------------------------------------

  adminAccounts(params?: { query?: string }): Promise<AccountAdministrationCollection> {
    const query = params?.query ? `?query=${encodeURIComponent(params.query)}` : "";
    return this.request<AccountAdministrationCollection>(`/admin/users${query}`);
  }

  adminChangeAccountState(
    userId: string,
    body: { state: string; reason?: string | null },
  ): Promise<AccountAdministrationResponse> {
    return this.request<AccountAdministrationResponse>(
      `/admin/users/${encodeURIComponent(userId)}/state`,
      { method: "POST", body },
    );
  }

  adminOrganizationRequests(): Promise<OrganizationReviewCollection> {
    return this.request<OrganizationReviewCollection>("/admin/organization-requests");
  }

  adminDecideOrganizationRequest(
    organizationId: string,
    body: { approve: boolean; reason?: string | null },
  ): Promise<OrganizationResponse> {
    return this.request<OrganizationResponse>(
      `/admin/organization-requests/${encodeURIComponent(organizationId)}/decision`,
      { method: "POST", body },
    );
  }


  // -- analyses, executions, jobs and schedules -----------------------------

  analyses(params?: {
    workspace_id?: string;
    project_id?: string;
    query?: string;
    state?: readonly string[];
  }): Promise<AnalysisCollection> {
    const search = new URLSearchParams();
    if (params?.workspace_id) search.set("workspace_id", params.workspace_id);
    if (params?.project_id) search.set("project_id", params.project_id);
    if (params?.query) search.set("query", params.query);
    for (const state of params?.state ?? []) search.append("state", state);
    const query = search.toString();
    return this.request<AnalysisCollection>(`/analyses${query ? `?${query}` : ""}`);
  }

  analysis(analysisId: string): Promise<AnalysisResponse> {
    return this.request<AnalysisResponse>(`/analyses/${encodeURIComponent(analysisId)}`);
  }

  createAnalysis(body: {
    project_id: string;
    name: string;
    kind: string;
    description?: string | null;
    capability_key?: string | null;
  }): Promise<AnalysisResponse> {
    return this.request<AnalysisResponse>("/analyses", { method: "POST", body });
  }

  changeAnalysisState(analysisId: string, body: { target: string }): Promise<AnalysisResponse> {
    return this.request<AnalysisResponse>(
      `/analyses/${encodeURIComponent(analysisId)}/state`,
      { method: "POST", body },
    );
  }

  analysisConfigurations(analysisId: string): Promise<ConfigurationCollection> {
    return this.request<ConfigurationCollection>(
      `/analyses/${encodeURIComponent(analysisId)}/configurations`,
    );
  }

  createAnalysisConfiguration(
    analysisId: string,
    body: {
      label?: string | null;
      inputs?: readonly { dataset_version_id: string; role: string }[];
      filtering_configuration?: Record<string, unknown> | null;
      ranking_configuration?: Record<string, unknown> | null;
      execution_parameters?: Record<string, unknown> | null;
      activate?: boolean;
    },
  ): Promise<ConfigurationResponse> {
    return this.request<ConfigurationResponse>(
      `/analyses/${encodeURIComponent(analysisId)}/configurations`,
      { method: "POST", body },
    );
  }

  activateAnalysisConfiguration(
    analysisId: string,
    configurationId: string,
  ): Promise<ConfigurationResponse> {
    return this.request<ConfigurationResponse>(
      `/analyses/${encodeURIComponent(analysisId)}/configurations/${encodeURIComponent(
        configurationId,
      )}/activation`,
      { method: "POST", body: {} },
    );
  }

  /** Requests an execution. The server queues durable work; nothing runs here. */
  requestExecution(
    analysisId: string,
    body: {
      configuration_id?: string | null;
      queue?: string | null;
      priority?: number | null;
      idempotency_key?: string | null;
    } = {},
  ): Promise<ExecutionResponse> {
    return this.request<ExecutionResponse>(
      `/analyses/${encodeURIComponent(analysisId)}/executions`,
      { method: "POST", body },
    );
  }

  executions(params?: {
    analysis_id?: string;
    workspace_id?: string;
    project_id?: string;
    state?: readonly string[];
  }): Promise<ExecutionCollection> {
    const search = new URLSearchParams();
    if (params?.analysis_id) search.set("analysis_id", params.analysis_id);
    if (params?.workspace_id) search.set("workspace_id", params.workspace_id);
    if (params?.project_id) search.set("project_id", params.project_id);
    for (const state of params?.state ?? []) search.append("state", state);
    const query = search.toString();
    return this.request<ExecutionCollection>(`/analysis-executions${query ? `?${query}` : ""}`);
  }

  execution(executionId: string): Promise<ExecutionResponse> {
    return this.request<ExecutionResponse>(
      `/analysis-executions/${encodeURIComponent(executionId)}`,
    );
  }

  executionProvenance(executionId: string): Promise<ExecutionProvenanceResponse> {
    return this.request<ExecutionProvenanceResponse>(
      `/analysis-executions/${encodeURIComponent(executionId)}/provenance`,
    );
  }

  cancelExecution(
    executionId: string,
    body: { reason?: string | null } = {},
  ): Promise<ExecutionResponse> {
    return this.request<ExecutionResponse>(
      `/analysis-executions/${encodeURIComponent(executionId)}/cancellation`,
      { method: "POST", body },
    );
  }

  jobs(params?: {
    workspace_id?: string;
    project_id?: string;
    state?: readonly string[];
    kind?: readonly string[];
    queue?: string;
  }): Promise<JobCollection> {
    const search = new URLSearchParams();
    if (params?.workspace_id) search.set("workspace_id", params.workspace_id);
    if (params?.project_id) search.set("project_id", params.project_id);
    if (params?.queue) search.set("queue", params.queue);
    for (const state of params?.state ?? []) search.append("state", state);
    for (const kind of params?.kind ?? []) search.append("kind", kind);
    const query = search.toString();
    return this.request<JobCollection>(`/jobs${query ? `?${query}` : ""}`);
  }

  job(jobId: string): Promise<JobResponse> {
    return this.request<JobResponse>(`/jobs/${encodeURIComponent(jobId)}`);
  }

  analysisSchedules(params?: {
    workspace_id?: string;
    project_id?: string;
    state?: readonly string[];
  }): Promise<ScheduleCollection> {
    const search = new URLSearchParams();
    if (params?.workspace_id) search.set("workspace_id", params.workspace_id);
    if (params?.project_id) search.set("project_id", params.project_id);
    for (const state of params?.state ?? []) search.append("state", state);
    const query = search.toString();
    return this.request<ScheduleCollection>(`/analysis-schedules${query ? `?${query}` : ""}`);
  }

  createAnalysisSchedule(body: {
    analysis_id: string;
    name: string;
    schedule_expression: string;
    timezone_name?: string;
    description?: string | null;
    configuration_id?: string | null;
    concurrency_policy?: string | null;
    missed_policy?: string | null;
    queue?: string | null;
    priority?: number | null;
    catch_up_limit?: number;
    enabled?: boolean;
  }): Promise<ScheduleResponse> {
    return this.request<ScheduleResponse>("/analysis-schedules", { method: "POST", body });
  }

  changeAnalysisScheduleState(
    scheduleId: string,
    body: { target: string },
  ): Promise<ScheduleResponse> {
    return this.request<ScheduleResponse>(
      `/analysis-schedules/${encodeURIComponent(scheduleId)}/state`,
      { method: "POST", body },
    );
  }

  // -- datasets, uploads, imports and validation ---------------------------

  datasets(params?: {
    workspace_id?: string;
    project_id?: string;
    query?: string;
    include_archived?: boolean;
  }): Promise<DatasetCollection> {
    const search = new URLSearchParams();
    if (params?.workspace_id) search.set("workspace_id", params.workspace_id);
    if (params?.project_id) search.set("project_id", params.project_id);
    if (params?.query) search.set("query", params.query);
    if (params?.include_archived) search.set("include_archived", "true");
    const query = search.toString();
    return this.request<DatasetCollection>(`/datasets${query ? `?${query}` : ""}`);
  }

  dataset(datasetId: string): Promise<DatasetResponse> {
    return this.request<DatasetResponse>(`/datasets/${encodeURIComponent(datasetId)}`);
  }

  createDataset(body: {
    workspace_id?: string | null;
    project_id?: string | null;
    name: string;
    kind: string;
    description?: string | null;
    reference_build_declared?: string;
  }): Promise<DatasetResponse> {
    return this.request<DatasetResponse>("/datasets", { method: "POST", body });
  }

  changeDatasetState(
    datasetId: string,
    body: { target_state: string; reason?: string | null },
  ): Promise<DatasetResponse> {
    return this.request<DatasetResponse>(
      `/datasets/${encodeURIComponent(datasetId)}/state`,
      { method: "POST", body },
    );
  }

  datasetVersions(datasetId: string): Promise<DatasetVersionCollection> {
    return this.request<DatasetVersionCollection>(
      `/datasets/${encodeURIComponent(datasetId)}/versions`,
    );
  }

  createDatasetVersion(
    datasetId: string,
    body: { notes?: string | null; reference_build_declared?: string | null } = {},
  ): Promise<DatasetVersionResponse> {
    return this.request<DatasetVersionResponse>(
      `/datasets/${encodeURIComponent(datasetId)}/versions`,
      { method: "POST", body },
    );
  }

  datasetImports(datasetId: string): Promise<ImportSessionCollection> {
    return this.request<ImportSessionCollection>(
      `/datasets/${encodeURIComponent(datasetId)}/imports`,
    );
  }

  /** Accepting or rejecting a validated version: an explicit human decision. */
  decideDatasetVersion(
    versionId: string,
    body: { accept: boolean; reason?: string | null },
  ): Promise<DatasetVersionResponse> {
    return this.request<DatasetVersionResponse>(
      `/dataset-versions/${encodeURIComponent(versionId)}/decision`,
      { method: "POST", body },
    );
  }

  openUploadSession(
    versionId: string,
    body: {
      filename: string;
      size_bytes: number;
      declared_format?: string | null;
      checksum_algorithm?: string;
      checksum_value?: string | null;
      content_type?: string | null;
    },
  ): Promise<UploadTicketResponse> {
    return this.request<UploadTicketResponse>(
      `/dataset-versions/${encodeURIComponent(versionId)}/uploads`,
      { method: "POST", body },
    );
  }

  completeUpload(sessionId: string): Promise<UploadSessionResponse> {
    return this.request<UploadSessionResponse>(
      `/uploads/${encodeURIComponent(sessionId)}/complete`,
      { method: "POST", body: {} },
    );
  }

  cancelUpload(sessionId: string, reason?: string | null): Promise<UploadSessionResponse> {
    return this.request<UploadSessionResponse>(
      `/uploads/${encodeURIComponent(sessionId)}/cancel`,
      { method: "POST", body: { reason: reason ?? null } },
    );
  }

  requestArtifactDownload(artifactId: string): Promise<DownloadGrantResponse> {
    return this.request<DownloadGrantResponse>(
      `/file-artifacts/${encodeURIComponent(artifactId)}/download`,
      { method: "POST", body: {} },
    );
  }

  openImportSession(
    artifactId: string,
    body: { idempotency_key?: string | null } = {},
  ): Promise<ImportSessionResponse> {
    return this.request<ImportSessionResponse>(
      `/file-artifacts/${encodeURIComponent(artifactId)}/imports`,
      { method: "POST", body: { file_artifact_id: artifactId, ...body } },
    );
  }

  importSession(sessionId: string): Promise<ImportSessionResponse> {
    return this.request<ImportSessionResponse>(`/imports/${encodeURIComponent(sessionId)}`);
  }

  confirmColumnMapping(
    sessionId: string,
    mappings: readonly ColumnMappingDecision[],
  ): Promise<ImportSessionResponse> {
    return this.request<ImportSessionResponse>(
      `/imports/${encodeURIComponent(sessionId)}/mapping`,
      { method: "PUT", body: { mappings } },
    );
  }

  submitImport(sessionId: string): Promise<ImportSessionResponse> {
    return this.request<ImportSessionResponse>(
      `/imports/${encodeURIComponent(sessionId)}/submit`,
      { method: "POST", body: {} },
    );
  }

  abandonImport(sessionId: string, reason?: string | null): Promise<ImportSessionResponse> {
    return this.request<ImportSessionResponse>(
      `/imports/${encodeURIComponent(sessionId)}/abandon`,
      { method: "POST", body: { reason: reason ?? null } },
    );
  }

  validationRuns(subjectType: string, subjectId: string): Promise<ValidationRunCollection> {
    const search = new URLSearchParams({
      subject_type: subjectType,
      subject_id: subjectId,
    });
    return this.request<ValidationRunCollection>(`/validation/runs?${search.toString()}`);
  }

  validationRun(runId: string): Promise<ValidationRunResponse> {
    return this.request<ValidationRunResponse>(
      `/validation/runs/${encodeURIComponent(runId)}`,
    );
  }

  /**
   * Transfers the bytes straight to object storage with the grant the backend
   * issued. Deliberately not a platform API call: no session cookie, no CSRF
   * token and no correlation header are sent to the storage origin, and the
   * platform still refuses the artifact afterwards if verification fails.
   */
  async transferBytes(uploadUrl: string, file: Blob, contentType?: string): Promise<void> {
    const response = await this.fetchImpl(uploadUrl, {
      method: "PUT",
      body: file,
      headers: contentType ? { "Content-Type": contentType } : undefined,
    });
    if (!response.ok) {
      throw new ApiError(
        response.status,
        "upload_transfer_failed",
        "The file could not be transferred to storage. Nothing was accepted.",
      );
    }
  }
}
