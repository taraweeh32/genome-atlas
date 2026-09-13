import { describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError, CORRELATION_ID_HEADER } from "@/lib/api-client";
import type { FrontendConfig } from "@/lib/config";

const config: FrontendConfig = {
  apiBaseUrl: "http://backend.test",
  apiPrefix: "/api/v1",
  environment: "test",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api client", () => {
  it("targets the versioned API and sends a correlation ID", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({ status: "ok", environment: "test", version: "0.1.0", checked_at: "now" }),
    );
    const client = new ApiClient({
      config,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      newCorrelationId: () => "corr-1",
    });

    await client.health();

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://backend.test/api/v1/health");
    expect((init.headers as Record<string, string>)[CORRELATION_ID_HEADER]).toBe("corr-1");
  });

  it("decodes the structured error envelope into a typed error", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: "validation_error",
            message: "Request validation failed.",
            details: { field: "name" },
            correlation_id: "corr-server",
          },
        },
        422,
      ),
    );
    const client = new ApiClient({ config, fetchImpl: fetchImpl as unknown as typeof fetch });

    const error = await client.readiness().catch((caught) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(422);
    expect(error.code).toBe("validation_error");
    expect(error.correlationId).toBe("corr-server");
    expect(error.isRetryable).toBe(false);
  });

  it("reports an unreachable API without leaking transport internals", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new Error("ECONNREFUSED 10.0.0.4:5432"));
    const client = new ApiClient({
      config,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      newCorrelationId: () => "corr-2",
    });

    const error: ApiError = await client.health().catch((caught) => caught);
    expect(error.code).toBe("network_error");
    expect(error.message).not.toContain("10.0.0.4");
    expect(error.correlationId).toBe("corr-2");
    expect(error.isRetryable).toBe(true);
  });

  it("treats 5xx and 429 as retryable and 4xx as operator/user errors", async () => {
    const cases: [number, boolean][] = [
      [503, true],
      [429, true],
      [403, false],
      [404, false],
    ];
    for (const [status, retryable] of cases) {
      const fetchImpl = vi.fn().mockResolvedValue(new Response("", { status }));
      const client = new ApiClient({ config, fetchImpl: fetchImpl as unknown as typeof fetch });
      const error: ApiError = await client.meta().catch((caught) => caught);
      expect(error.isRetryable).toBe(retryable);
    }
  });
});
