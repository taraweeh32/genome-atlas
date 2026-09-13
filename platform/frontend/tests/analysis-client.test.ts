import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "@/lib/api-client";
import type { FrontendConfig } from "@/lib/config";

const config: FrontendConfig = {
  apiBaseUrl: "http://backend.test",
  apiVersion: "v1",
  environment: "test",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function clientWith(fetchImpl: unknown) {
  return new ApiClient({
    config,
    fetchImpl: fetchImpl as typeof fetch,
    csrfTokenReader: () => "csrf-token",
    newCorrelationId: () => "corr-1",
  });
}

const emptyPage = { items: [], page: { number: 1, size: 50, total: 0 } };

describe("analysis, execution and job API client", () => {
  it("scopes an analysis list instead of asking for everything", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(emptyPage));
    await clientWith(fetchImpl).analyses({
      workspace_id: "wsp_1",
      state: ["active", "ready"],
    });

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe(
      "http://backend.test/api/v1/analyses?workspace_id=wsp_1&state=active&state=ready",
    );
  });

  it("requests an execution as a server-side queue operation, not a local run", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ id: "aex_1", state: "queued", can_cancel: true }));
    const execution = await clientWith(fetchImpl).requestExecution("ana_1", {
      idempotency_key: "req-1",
    });

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://backend.test/api/v1/analyses/ana_1/executions");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf-token");
    expect(JSON.parse(init.body as string)).toEqual({ idempotency_key: "req-1" });
    // The response is a queued execution. No result is implied by requesting one.
    expect(execution.state).toBe("queued");
  });

  it("asks the server to cancel, treating cancellation as a request", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ id: "aex_1", state: "cancel_requested" }));
    const execution = await clientWith(fetchImpl).cancelExecution("aex_1", { reason: "superseded" });

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://backend.test/api/v1/analysis-executions/aex_1/cancellation");
    expect(init.method).toBe("POST");
    expect(execution.state).toBe("cancel_requested");
  });

  it("reads execution provenance without inventing missing recorded facts", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        execution: { id: "aex_1", compute_node_id: null },
        scientific_executions: [
          { id: "sex_1", engine_version: null, container_image_digest: null, artifacts: [] },
        ],
        configuration_snapshot: {},
      }),
    );
    const provenance = await clientWith(fetchImpl).executionProvenance("aex_1");

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://backend.test/api/v1/analysis-executions/aex_1/provenance");
    expect(provenance.execution.compute_node_id).toBeNull();
    expect(provenance.scientific_executions[0].engine_version).toBeNull();
  });

  it("lists jobs scoped to a workspace and filtered by recorded state", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(emptyPage));
    await clientWith(fetchImpl).jobs({ workspace_id: "wsp_1", state: ["retry_waiting"] });

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://backend.test/api/v1/jobs?workspace_id=wsp_1&state=retry_waiting");
  });

  it("creates a schedule with an explicit expression and timezone", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ id: "sch_1" }));
    await clientWith(fetchImpl).createAnalysisSchedule({
      analysis_id: "ana_1",
      name: "Nightly",
      schedule_expression: "daily:02:30",
      timezone_name: "Europe/Berlin",
    });

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://backend.test/api/v1/analysis-schedules");
    expect(JSON.parse(init.body as string)).toEqual({
      analysis_id: "ana_1",
      name: "Nightly",
      schedule_expression: "daily:02:30",
      timezone_name: "Europe/Berlin",
    });
  });
});
