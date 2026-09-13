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

export interface RequestOptions {
  readonly method?: "GET" | "POST" | "PATCH" | "DELETE";
  readonly body?: unknown;
  readonly correlationId?: string;
  readonly signal?: AbortSignal;
}

export interface ApiClientOptions {
  readonly config?: FrontendConfig;
  readonly fetchImpl?: typeof fetch;
  readonly newCorrelationId?: () => string;
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

  constructor(options: ApiClientOptions = {}) {
    this.config = options.config ?? loadFrontendConfig();
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
    this.newCorrelationId = options.newCorrelationId ?? defaultCorrelationId;
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

    let response: Response;
    try {
      response = await this.fetchImpl(apiUrl(this.config, path), {
        method: options.method ?? "GET",
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
}
