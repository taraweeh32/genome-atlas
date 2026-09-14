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

describe("filtering, prioritization and saved-view API client", () => {
  it("narrows the field dictionary to a named result surface", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ version: "1.0.0", fields: [], result_set_id: "rst_1", available_field_ids: [] }),
      );
    await clientWith(fetchImpl).filterFields({ result_set_id: "rst_1" });

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://backend.test/api/v1/filter-fields?result_set_id=rst_1");
  });

  it("asks for a bounded value search and never a whole distinct list", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        field_id: "gene_symbol",
        result_set_id: "rst_1",
        values: [],
        truncated: true,
        field_dictionary_version: "1.0.0",
      }),
    );
    await clientWith(fetchImpl).filterFieldValues("gene_symbol", {
      result_set_id: "rst_1",
      search: "CF",
      limit: 20,
    });

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe(
      "http://backend.test/api/v1/filter-fields/gene_symbol/values?result_set_id=rst_1&search=CF&limit=20",
    );
  });

  it("sends filtering and prioritization as separate payloads", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        result_set_id: "rst_1",
        columns: [],
        field_ids: [],
        rows: [],
        returned_count: 0,
        total_count: null,
        next_cursor: null,
        execution: {},
        ranking_execution: null,
        ranking_window_exceeded: false,
        ranking_window_rows: null,
      }),
    );
    await clientWith(fetchImpl).queryVariants({
      result_set_id: "rst_1",
      filter: {
        expression: {
          kind: "group",
          operator: "and",
          children: [
            {
              kind: "condition",
              field_id: "gene_symbol",
              operator: "in",
              values: ["CFTR"],
            },
          ],
        },
      },
      ranking: {
        configuration: {
          method_id: "weighted_field_score",
          method_version: "1.0.0",
          components: [
            { field_id: "allele_frequency", kind: "numeric_ascending", weight: 1 },
          ],
        },
      },
      page_size: 50,
    });

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://backend.test/api/v1/variants/query");
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    // The two configurations travel side by side: a ranking never appears inside
    // a filter, so it can never narrow the set.
    expect(Object.keys(body).sort()).toEqual([
      "filter",
      "page_size",
      "ranking",
      "result_set_id",
    ]);
    expect(body.filter).not.toHaveProperty("configuration");
    expect(body.ranking).not.toHaveProperty("expression");
  });

  it("routes an oversized query to the durable job endpoint", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          job_id: "job_1",
          result_set_id: "rst_1",
          effective_hash: "hash",
          field_dictionary_version: "1.0.0",
          max_rows: 100000,
        },
        202,
      ),
    );
    await clientWith(fetchImpl).deferVariantQuery({ result_set_id: "rst_1" });

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://backend.test/api/v1/variants/query/deferred");
    expect(init.method).toBe("POST");
  });

  it("carries the seen version on every configuration mutation", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}));
    await clientWith(fetchImpl).addQueryConfigurationVersion("filters", "flt_1", {
      expected_version: 3,
      content: { expression: { kind: "group", operator: "and", children: [] } },
      change_note: "narrowed the gene list",
    });

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://backend.test/api/v1/filters/flt_1/versions");
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    // A stale write must be refusable server-side, so the version the caller saw
    // is always part of the request.
    expect(body.expected_version).toBe(3);
  });

  it("reads each configuration family from its own collection", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(emptyPage));
    const client = clientWith(fetchImpl);
    await client.queryConfigurations("filter-presets");
    await client.queryConfigurations("ranking-presets", { page: 2, size: 25 });

    expect(fetchImpl.mock.calls[0][0]).toBe("http://backend.test/api/v1/filter-presets");
    expect(fetchImpl.mock.calls[1][0]).toBe(
      "http://backend.test/api/v1/ranking-presets?page=2&size=25",
    );
  });

  it("reads the platform limits from the administration namespace", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}));
    await clientWith(fetchImpl).adminQueryLimits();

    expect(fetchImpl.mock.calls[0][0]).toBe(
      "http://backend.test/api/v1/administration/query/limits",
    );
  });
});
