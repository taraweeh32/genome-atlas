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

describe("result and variant API client", () => {
  it("scopes a result-set list instead of asking for everything", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(emptyPage));
    await clientWith(fetchImpl).resultSets({
      workspace_id: "wsp_1",
      state: ["available", "superseded"],
    });

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe(
      "http://backend.test/api/v1/result-sets?workspace_id=wsp_1&state=available&state=superseded",
    );
  });

  it("asks for a bounded content window, never a whole surface", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        result_set_id: "rst_1",
        state: "available",
        columns: ["variant_id"],
        rows: [["var_1"]],
        total_rows: 1,
        offset: 100,
        is_development_payload: true,
      }),
    );
    const page = await clientWith(fetchImpl).resultContent("rst_1", {
      offset: 100,
      limit: 50,
    });

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://backend.test/api/v1/result-sets/rst_1/content?offset=100&limit=50");
    // The development marker travels with the content and is never dropped.
    expect(page.is_development_payload).toBe(true);
  });

  it("treats an artifact download as a server-issued grant request", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        artifact_id: "rar_1",
        artifact_key: "table.parquet",
        url: "https://storage.test/signed",
        expires_in_seconds: 300,
      }),
    );
    const grant = await clientWith(fetchImpl).requestArtifactDownload("rst_1", "rar_1");

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(
      "http://backend.test/api/v1/result-sets/rst_1/artifacts/rar_1/download",
    );
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf-token");
    // The platform hands back a short-lived grant; bytes never flow through it.
    expect(grant.url).toBe("https://storage.test/signed");
    expect(grant.expires_in_seconds).toBe(300);
  });

  it("withdraws a surface through the administrative route only", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ id: "rst_1", state: "invalidated" }));
    await clientWith(fetchImpl).adminInvalidateResultSet("rst_1", { reason: "bad reference" });

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://backend.test/api/v1/administration/result-sets/rst_1/invalidate");
    expect(JSON.parse(init.body as string)).toEqual({ reason: "bad reference" });
  });

  it("always reads variants through one dataset version", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(emptyPage));
    await clientWith(fetchImpl).variants({
      dataset_version_id: "dsv_1",
      contig: "chr1",
      position_from: 100,
      position_to: 200,
    });

    const [listUrl] = fetchImpl.mock.calls[0];
    expect(listUrl).toBe(
      "http://backend.test/api/v1/variants?dataset_version_id=dsv_1&contig=chr1&position_from=100&position_to=200",
    );

    await clientWith(fetchImpl).variant("var_1", "dsv_1");
    const [detailUrl] = fetchImpl.mock.calls[1];
    expect(detailUrl).toBe("http://backend.test/api/v1/variants/var_1?dataset_version_id=dsv_1");
  });

  it("surfaces the backend refusal for an out-of-scope result set", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: "not_found",
            message: "The result set does not exist or is not visible to you.",
            correlation_id: "corr-1",
          },
        },
        404,
      ),
    );

    await expect(clientWith(fetchImpl).resultSet("rst_other")).rejects.toMatchObject({
      status: 404,
      code: "not_found",
    });
  });
});
