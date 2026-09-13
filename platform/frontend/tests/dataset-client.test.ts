import { describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError } from "@/lib/api-client";
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

function clientWith(fetchImpl: unknown, csrf: string | null = "csrf-token") {
  return new ApiClient({
    config,
    fetchImpl: fetchImpl as typeof fetch,
    csrfTokenReader: () => csrf,
    newCorrelationId: () => "corr-1",
  });
}

describe("dataset API client", () => {
  it("scopes a dataset list by workspace instead of asking for everything", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ items: [], page: { number: 1, size: 50, total: 0 } }));
    await clientWith(fetchImpl).datasets({ workspace_id: "wsp_1", include_archived: true });

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe(
      "http://backend.test/api/v1/datasets?workspace_id=wsp_1&include_archived=true",
    );
  });

  it("sends the CSRF token on state-changing dataset requests", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ id: "dst_1" }));
    await clientWith(fetchImpl).createDataset({
      workspace_id: "wsp_1",
      name: "Cohort",
      kind: "variant_calls",
    });

    const [, init] = fetchImpl.mock.calls[0];
    const headers = init.headers as Record<string, string>;
    expect(init.method).toBe("POST");
    expect(headers["X-CSRF-Token"]).toBe("csrf-token");
    expect(init.credentials).toBe("include");
  });

  it("transfers bytes to the storage grant without sending session credentials", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
    await clientWith(fetchImpl).transferBytes(
      "https://storage.test/signed-put",
      new Blob(["chrom\tpos\n"]),
      "text/tab-separated-values",
    );

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://storage.test/signed-put");
    expect(init.method).toBe("PUT");
    // The storage origin must never receive the session cookie or the CSRF token.
    expect(init.credentials).toBeUndefined();
    expect(init.headers).toEqual({ "Content-Type": "text/tab-separated-values" });
  });

  it("reports a refused transfer as a failure rather than a silent success", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response("denied", { status: 403 }));
    const error = await clientWith(fetchImpl)
      .transferBytes("https://storage.test/signed-put", new Blob(["x"]))
      .catch((caught) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("upload_transfer_failed");
  });

  it("confirms a column mapping as an explicit human decision payload", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ id: "imp_1" }));
    await clientWith(fetchImpl).confirmColumnMapping("imp_1", [
      { source_column_index: 4, source_column_name: "depth", target_concept: "read_depth" },
    ]);

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://backend.test/api/v1/imports/imp_1/mapping");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({
      mappings: [
        { source_column_index: 4, source_column_name: "depth", target_concept: "read_depth" },
      ],
    });
  });

  it("asks for a download grant instead of streaming bytes through the API", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        file_artifact_id: "fil_1",
        filename: "cohort.tsv",
        download_url: "https://storage.test/signed-get",
        expires_in_seconds: 300,
      }),
    );
    const grant = await clientWith(fetchImpl).requestArtifactDownload("fil_1");

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://backend.test/api/v1/file-artifacts/fil_1/download");
    expect(init.method).toBe("POST");
    expect(grant.download_url).toBe("https://storage.test/signed-get");
    expect(grant.expires_in_seconds).toBe(300);
  });
});
