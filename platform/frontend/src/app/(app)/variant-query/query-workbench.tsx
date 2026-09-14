"use client";

/**
 * The variant query workbench: filter, prioritize, page, arrange, save.
 *
 * Everything scientific here happens on the server. The browser sends a
 * structured filter, an optional prioritization configuration, a page size and a
 * cursor; the server authorizes the result set, validates both configurations,
 * executes them against the stored analytical surface and returns one bounded
 * page plus the record of exactly what ran. No dataset is downloaded to be
 * filtered locally, and no value shown here is computed in the browser.
 *
 * Three distinctions are kept visible because conflating them would misreport
 * the data:
 *
 * - **Sorting is not ranking.** Sorting reorders by one recorded column.
 *   Prioritization computes a declared score. They are separate controls and
 *   separate records.
 * - **A count that was not computed is unknown**, not zero. Totals are only
 *   requested on demand and displayed as reported.
 * - **An unreported value is unreported**, never blank-as-zero or false.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  FilterBuilder,
  countConditions,
  emptyGroup,
  toPayload,
  type DraftGroup,
} from "@/components/query/filter-builder";
import {
  RankingControls,
  emptyRanking,
  toRankingPayload,
  type DraftRanking,
} from "@/components/query/ranking-controls";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useToasts } from "@/components/ui/toast";
import { useWorkspace } from "@/context/workspace-context";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient, ApiError } from "@/lib/api-client";
import type {
  FilterGroupPayload,
  FilterValidationIssueResponse,
  SavedViewResponse,
  VariantQueryResponse,
} from "@/lib/query-types";
import queryStyles from "@/components/query/query.module.css";
import styles from "../results/results.module.css";

const PAGE_SIZES = [25, 50, 100, 200] as const;

/** The columns offered before a field dictionary has been read. */
const DEFAULT_COLUMNS = [
  "contig",
  "position",
  "reference_allele",
  "alternate_allele",
  "gene_symbol",
  "consequence_term",
] as const;

function cellText(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function QueryWorkbench() {
  const client = useMemo(() => new ApiClient(), []);
  const { publish } = useToasts();
  const { activeWorkspace } = useWorkspace();
  const workspaceId = activeWorkspace?.id ?? null;

  const [resultSetId, setResultSetId] = useState("");
  const [filterDraft, setFilterDraft] = useState<DraftGroup>(() => emptyGroup("and"));
  const [rankingDraft, setRankingDraft] = useState<DraftRanking>(() =>
    emptyRanking(undefined),
  );
  const [presetId, setPresetId] = useState("");
  const [savedFilterId, setSavedFilterId] = useState("");
  const [rankingPresetId, setRankingPresetId] = useState("");
  const [columns, setColumns] = useState<readonly string[]>([...DEFAULT_COLUMNS]);
  const [pageSize, setPageSize] = useState<number>(50);
  const [sortFieldId, setSortFieldId] = useState("");
  const [sortDescending, setSortDescending] = useState(false);
  const [includeTotal, setIncludeTotal] = useState(false);
  const [cursor, setCursor] = useState<string | null>(null);
  const [cursorStack, setCursorStack] = useState<readonly string[]>([]);
  const [issues, setIssues] = useState<readonly FilterValidationIssueResponse[]>([]);
  const [page, setPage] = useState<VariantQueryResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [correlationId, setCorrelationId] = useState<string | null>(null);

  const resultSets = useApiResource(
    () =>
      workspaceId
        ? client.resultSets({ workspace_id: workspaceId, state: ["available"] })
        : Promise.resolve({ items: [], page: { number: 1, size: 0, total: 0 } }),
    [client, workspaceId],
  );
  const dictionary = useApiResource(
    () => client.filterFields(resultSetId ? { result_set_id: resultSetId } : {}),
    [client, resultSetId],
  );
  const methods = useApiResource(() => client.rankingMethods(), [client]);
  const savedFilters = useApiResource(
    () => client.queryConfigurations("filters", { size: 50 }),
    [client],
  );
  const presets = useApiResource(
    () => client.queryConfigurations("filter-presets", { size: 50 }),
    [client],
  );
  const rankingPresets = useApiResource(
    () => client.queryConfigurations("ranking-presets", { size: 50 }),
    [client],
  );
  const views = useApiResource(() => client.savedViews({ size: 50 }), [client]);

  const fields = useMemo(() => {
    const all = dictionary.data?.fields ?? [];
    const available = dictionary.data?.available_field_ids ?? null;
    // A named result set narrows the dictionary to the columns that surface
    // actually carries. With no surface named, every published field is offered.
    return available === null
      ? all.filter((field) => field.filterable && field.available)
      : all.filter(
          (field) => field.filterable && field.available && available.includes(field.id),
        );
  }, [dictionary.data]);

  const sortableFields = useMemo(
    () => (dictionary.data?.fields ?? []).filter((field) => field.sortable),
    [dictionary.data],
  );

  const filterPayload = useMemo(() => {
    const map = new Map((dictionary.data?.fields ?? []).map((f) => [f.id, f] as const));
    const payload = toPayload(filterDraft, map);
    return payload && payload.kind === "group" ? (payload as FilterGroupPayload) : null;
  }, [dictionary.data, filterDraft]);

  const rankingPayload = useMemo(() => toRankingPayload(rankingDraft), [rankingDraft]);

  const run = useCallback(
    async (nextCursor: string | null, stack: readonly string[]) => {
      if (!resultSetId) return;
      setRunning(true);
      setFailure(null);
      setCorrelationId(null);
      try {
        const response = await client.queryVariants({
          result_set_id: resultSetId,
          ...(filterPayload || savedFilterId || presetId
            ? {
                filter: {
                  ...(filterPayload ? { expression: filterPayload } : {}),
                  ...(savedFilterId ? { filter_definition_id: savedFilterId } : {}),
                  ...(presetId ? { filter_preset_id: presetId } : {}),
                },
              }
            : {}),
          ...(rankingPayload || rankingPresetId
            ? {
                ranking: {
                  ...(rankingPayload ? { configuration: rankingPayload } : {}),
                  ...(rankingPresetId ? { ranking_preset_id: rankingPresetId } : {}),
                },
              }
            : {}),
          ...(columns.length > 0 ? { field_ids: columns } : {}),
          page_size: pageSize,
          ...(nextCursor ? { cursor: nextCursor } : {}),
          ...(sortFieldId ? { sort_field_id: sortFieldId, sort_descending: sortDescending } : {}),
          include_total: includeTotal,
        });
        setPage(response);
        setIssues([]);
        setCursor(nextCursor);
        setCursorStack(stack);
      } catch (cause) {
        const error = cause instanceof ApiError ? cause : null;
        const detail = error?.details as
          | { issues?: readonly FilterValidationIssueResponse[] }
          | undefined;
        setIssues(detail?.issues ?? []);
        setFailure(error?.message ?? "The query could not be executed.");
        setCorrelationId(error?.correlationId ?? null);
      } finally {
        setRunning(false);
      }
    },
    [
      client,
      columns,
      filterPayload,
      includeTotal,
      pageSize,
      presetId,
      rankingPayload,
      rankingPresetId,
      resultSetId,
      savedFilterId,
      sortDescending,
      sortFieldId,
    ],
  );

  useEffect(() => {
    // Changing the surface invalidates every cursor: a cursor is only meaningful
    // for the exact query that produced it.
    setPage(null);
    setCursor(null);
    setCursorStack([]);
  }, [resultSetId]);

  async function validate() {
    if (!filterPayload) {
      setIssues([]);
      publish({ tone: "info", title: "The filter is empty; nothing to validate." });
      return;
    }
    try {
      const response = await client.validateFilter(
        filterPayload as unknown as Record<string, unknown>,
      );
      setIssues(response.issues);
      publish({
        tone: response.valid ? "success" : "danger",
        title: response.valid ? "The filter is valid" : "The filter has problems",
        description: response.valid
          ? `${response.condition_count} condition(s), depth ${response.depth}, dictionary ${response.field_dictionary_version}.`
          : `${response.issues.length} issue(s) reported.`,
      });
    } catch (cause) {
      const error = cause instanceof ApiError ? cause : null;
      publish({
        tone: "danger",
        title: "Validation failed",
        description: error?.message,
        correlationId: error?.correlationId,
      });
    }
  }

  async function saveFilter() {
    if (!filterPayload) return;
    const name = window.prompt("Name for this saved filter");
    if (!name) return;
    try {
      await client.createQueryConfiguration("filters", {
        name,
        scope: "personal",
        content: { expression: filterPayload },
        publish: true,
      });
      publish({ tone: "success", title: "Saved filter created at version 1" });
      savedFilters.reload();
    } catch (cause) {
      const error = cause instanceof ApiError ? cause : null;
      publish({
        tone: "danger",
        title: "The filter was not saved",
        description: error?.message,
        correlationId: error?.correlationId,
      });
    }
  }

  async function saveRanking() {
    if (!rankingPayload) return;
    const name = window.prompt("Name for this prioritization configuration");
    if (!name) return;
    try {
      await client.createQueryConfiguration("rankings", {
        name,
        scope: "personal",
        content: rankingPayload as unknown as Record<string, unknown>,
        publish: true,
      });
      publish({ tone: "success", title: "Prioritization saved at version 1" });
    } catch (cause) {
      const error = cause instanceof ApiError ? cause : null;
      publish({
        tone: "danger",
        title: "The prioritization was not saved",
        description: error?.message,
        correlationId: error?.correlationId,
      });
    }
  }

  async function saveView() {
    const name = window.prompt("Name for this table view");
    if (!name) return;
    try {
      await client.createSavedView({
        name,
        scope: "personal",
        columns,
        page_size: pageSize,
        ...(sortFieldId ? { sort_field_id: sortFieldId, sort_descending: sortDescending } : {}),
        ...(savedFilterId ? { default_filter_definition_id: savedFilterId } : {}),
        ...(presetId ? { default_filter_preset_id: presetId } : {}),
        ...(rankingPresetId ? { default_ranking_preset_id: rankingPresetId } : {}),
      });
      publish({ tone: "success", title: "View saved" });
      views.reload();
    } catch (cause) {
      const error = cause instanceof ApiError ? cause : null;
      publish({
        tone: "danger",
        title: "The view was not saved",
        description: error?.message,
        correlationId: error?.correlationId,
      });
    }
  }

  function applyView(view: SavedViewResponse) {
    setColumns(view.columns.length > 0 ? view.columns : [...DEFAULT_COLUMNS]);
    setPageSize(view.page_size);
    setSortFieldId(view.sort_field_id ?? "");
    setSortDescending(view.sort_descending);
    setSavedFilterId(view.default_filter_definition_id ?? "");
    setPresetId(view.default_filter_preset_id ?? "");
    setRankingPresetId(view.default_ranking_preset_id ?? "");
  }

  async function defer() {
    if (!resultSetId) return;
    try {
      const response = await client.deferVariantQuery({
        result_set_id: resultSetId,
        ...(filterPayload ? { filter: { expression: filterPayload } } : {}),
        ...(rankingPayload ? { ranking: { configuration: rankingPayload } } : {}),
        ...(columns.length > 0 ? { field_ids: columns } : {}),
        ...(sortFieldId ? { sort_field_id: sortFieldId, sort_descending: sortDescending } : {}),
      });
      publish({
        tone: "success",
        title: "Query queued as a background job",
        description: `Job ${response.job_id}. The full result is written to a stored file, up to ${response.max_rows} rows.`,
      });
    } catch (cause) {
      const error = cause instanceof ApiError ? cause : null;
      publish({
        tone: "danger",
        title: "The query was not queued",
        description: error?.message,
        correlationId: error?.correlationId,
      });
    }
  }

  if (resultSets.status === "loading") return <LoadingState label="Loading result sets" />;
  if (resultSets.status === "error") {
    return (
      <ErrorState
        title="Result sets could not be read"
        description={resultSets.error ?? ""}
        correlationId={resultSets.correlationId ?? undefined}
        action={
          <Button type="button" variant="secondary" onClick={resultSets.reload}>
            Retry
          </Button>
        }
      />
    );
  }

  const available = resultSets.data?.items ?? [];

  return (
    <div className={queryStyles.builder}>
      <Card
        title="Result surface"
        description="A variant query always runs against one result set you are authorized to read."
      >
        {available.length === 0 ? (
          <EmptyState
            title="No readable result set"
            description="Filtering reads a result set produced by an analysis execution. None is available in this workspace yet."
          />
        ) : (
          <div className={queryStyles.groupHeader}>
            <label className={`${queryStyles.control} ${queryStyles.controlWide}`}>
              <span className={queryStyles.controlLabel}>Result set</span>
              <select
                className={queryStyles.select}
                value={resultSetId}
                onChange={(event) => setResultSetId(event.target.value)}
              >
                <option value="">Select a result set…</option>
                {available.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.result_key} — {item.row_count ?? "row count unreported"}
                  </option>
                ))}
              </select>
            </label>
            <label className={queryStyles.control}>
              <span className={queryStyles.controlLabel}>Rows per page</span>
              <select
                className={queryStyles.select}
                value={pageSize}
                onChange={(event) => setPageSize(Number(event.target.value))}
              >
                {PAGE_SIZES.map((size) => (
                  <option key={size} value={size}>
                    {size}
                  </option>
                ))}
              </select>
            </label>
            <label className={queryStyles.control}>
              <span className={queryStyles.controlLabel}>Sort by column</span>
              <select
                className={queryStyles.select}
                value={sortFieldId}
                onChange={(event) => setSortFieldId(event.target.value)}
              >
                <option value="">Stable default order</option>
                {sortableFields.map((field) => (
                  <option key={field.id} value={field.id}>
                    {field.label}
                  </option>
                ))}
              </select>
            </label>
            <label className={queryStyles.checkbox}>
              <input
                type="checkbox"
                checked={sortDescending}
                onChange={(event) => setSortDescending(event.target.checked)}
              />
              Descending
            </label>
            <label className={queryStyles.checkbox}>
              <input
                type="checkbox"
                checked={includeTotal}
                onChange={(event) => setIncludeTotal(event.target.checked)}
              />
              Count all matches (slower)
            </label>
          </div>
        )}
      </Card>

      <Card
        title="Filter"
        description="Conditions are combined with AND, OR and NOT. Filtering decides which rows are returned and never produces a score."
      >
        {dictionary.status === "loading" ? (
          <LoadingState label="Loading the field dictionary" />
        ) : dictionary.status === "error" ? (
          <ErrorState
            title="The field dictionary could not be read"
            description={dictionary.error ?? ""}
            correlationId={dictionary.correlationId ?? undefined}
        action={
          <Button type="button" variant="secondary" onClick={dictionary.reload}>
            Retry
          </Button>
        }
          />
        ) : (
          <>
            <div className={queryStyles.groupHeader}>
              <label className={`${queryStyles.control} ${queryStyles.controlWide}`}>
                <span className={queryStyles.controlLabel}>Preset</span>
                <select
                  className={queryStyles.select}
                  value={presetId}
                  onChange={(event) => setPresetId(event.target.value)}
                >
                  <option value="">No preset</option>
                  {(presets.data?.items ?? []).map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name} — {item.scope} (v{item.latest_version_number})
                    </option>
                  ))}
                </select>
              </label>
              <label className={`${queryStyles.control} ${queryStyles.controlWide}`}>
                <span className={queryStyles.controlLabel}>Saved filter</span>
                <select
                  className={queryStyles.select}
                  value={savedFilterId}
                  onChange={(event) => setSavedFilterId(event.target.value)}
                >
                  <option value="">No saved filter</option>
                  {(savedFilters.data?.items ?? []).map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name} — {item.scope} (v{item.latest_version_number})
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {presetId || savedFilterId ? (
              <p className={queryStyles.hint}>
                The selected definition is combined with the conditions below
                without being modified. The execution record keeps the preset
                identity, its version and your additions separately.
              </p>
            ) : null}
            <FilterBuilder
              root={filterDraft}
              fields={fields}
              issues={issues}
              resultSetId={resultSetId || null}
              onChange={setFilterDraft}
            />
            <div className={queryStyles.rowActions}>
              <Button type="button" variant="secondary" onClick={() => void validate()}>
                Validate
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => void saveFilter()}
                disabled={!filterPayload}
              >
                Save as filter
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => setFilterDraft(emptyGroup("and"))}
              >
                Clear
              </Button>
            </div>
            <p className={queryStyles.hint}>
              {countConditions(filterDraft)} condition(s) in this filter. Field
              dictionary {dictionary.data?.version}.
            </p>
          </>
        )}
      </Card>

      <Card
        title="Prioritization"
        description="An optional prioritization score orders the rows the filter returned. It never changes which rows are returned, and it is not a clinical assessment."
      >
        {methods.status === "error" ? (
          <ErrorState
            title="Prioritization methods could not be read"
            description={methods.error ?? ""}
            correlationId={methods.correlationId ?? undefined}
        action={
          <Button type="button" variant="secondary" onClick={methods.reload}>
            Retry
          </Button>
        }
          />
        ) : (
          <>
            <label className={`${queryStyles.control} ${queryStyles.controlWide}`}>
              <span className={queryStyles.controlLabel}>Prioritization preset</span>
              <select
                className={queryStyles.select}
                value={rankingPresetId}
                onChange={(event) => setRankingPresetId(event.target.value)}
              >
                <option value="">No preset</option>
                {(rankingPresets.data?.items ?? []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} — {item.scope} (v{item.latest_version_number})
                  </option>
                ))}
              </select>
            </label>
            <RankingControls
              draft={rankingDraft}
              methods={methods.data?.items ?? []}
              fields={sortableFields}
              onChange={setRankingDraft}
            />
            <div className={queryStyles.rowActions}>
              <Button
                type="button"
                variant="secondary"
                onClick={() => void saveRanking()}
                disabled={!rankingPayload}
              >
                Save as prioritization
              </Button>
            </div>
          </>
        )}
      </Card>

      <Card
        title="Columns and views"
        description="Column choice is presentation only: it changes what is displayed, never the recorded data."
      >
        <div className={queryStyles.columnGrid}>
          {(dictionary.data?.fields ?? []).map((field) => (
            <label key={field.id} className={queryStyles.checkbox}>
              <input
                type="checkbox"
                checked={columns.includes(field.id)}
                onChange={(event) =>
                  setColumns((current) =>
                    event.target.checked
                      ? [...current, field.id]
                      : current.filter((id) => id !== field.id),
                  )
                }
              />
              {field.label}
            </label>
          ))}
        </div>
        <div className={queryStyles.rowActions}>
          <Button type="button" variant="secondary" onClick={() => void saveView()}>
            Save this view
          </Button>
        </div>
        <div className={queryStyles.chips}>
          {(views.data?.items ?? []).map((view) => (
            <span key={view.id} className={queryStyles.chip}>
              {view.name}
              <button type="button" onClick={() => applyView(view)}>
                apply
              </button>
            </span>
          ))}
        </div>
      </Card>

      <Card
        title="Results"
        description="One bounded page, ordered deterministically, read from the stored analytical surface."
      >
        <div className={queryStyles.rowActions}>
          <Button
            type="button"
            onClick={() => void run(null, [])}
            disabled={!resultSetId || running}
          >
            {running ? "Running…" : "Run query"}
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={() => void defer()}
            disabled={!resultSetId}
          >
            Run as background job
          </Button>
        </div>

        {failure ? (
          <ErrorState
            title="The query was refused"
            description={failure}
            correlationId={correlationId ?? undefined}
          />
        ) : null}

        {page === null ? (
          <EmptyState
            title="No query has been run"
            description="Choose a result set, assemble a filter and run the query. Nothing is filtered in the browser."
          />
        ) : (
          <>
            <div className={queryStyles.summary}>
              <span className={queryStyles.summaryItem}>
                Returned
                <span className={queryStyles.summaryValue}>{page.returned_count}</span>
              </span>
              <span className={queryStyles.summaryItem}>
                Total matches
                <span className={queryStyles.summaryValue}>
                  {page.total_count ?? "not counted"}
                </span>
              </span>
              <span className={queryStyles.summaryItem}>
                Outcome
                <span className={queryStyles.summaryValue}>{page.execution.outcome}</span>
              </span>
              <span className={queryStyles.summaryItem}>
                Filter hash
                <span className={queryStyles.summaryValue}>
                  {page.execution.effective_hash}
                </span>
              </span>
              <span className={queryStyles.summaryItem}>
                Dictionary
                <span className={queryStyles.summaryValue}>
                  {page.execution.field_dictionary_version}
                </span>
              </span>
              {page.ranking_execution ? (
                <>
                  <span className={queryStyles.summaryItem}>
                    Prioritized
                    <span className={queryStyles.summaryValue}>
                      {page.ranking_execution.method_id} v
                      {page.ranking_execution.method_version}
                    </span>
                  </span>
                  <span className={queryStyles.summaryItem}>
                    Scored / unscored
                    <span className={queryStyles.summaryValue}>
                      {page.ranking_execution.scored_count} /{" "}
                      {page.ranking_execution.unscored_count}
                    </span>
                  </span>
                </>
              ) : null}
            </div>

            {page.ranking_window_exceeded ? (
              <p className={queryStyles.issue}>
                More rows matched than the prioritization window of{" "}
                {page.ranking_window_rows} rows. The order shown covers that
                window only — narrow the filter or run the query as a background
                job for the complete ordering.
              </p>
            ) : null}

            {page.rows.length === 0 ? (
              <EmptyState
                title="No rows matched"
                description="The filter excluded every row of this surface. Rows that never reported a filtered field are excluded because the value is missing."
              />
            ) : (
              <div className={styles.scroll}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      {page.columns.map((column) => (
                        <th key={column} scope="col">
                          {column.replace(/_/g, " ")}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {page.rows.map((row, index) => (
                      <tr key={index}>
                        {page.columns.map((column) => {
                          const text = cellText(row[column]);
                          return (
                            <td key={column}>
                              {text === null ? (
                                <span className={styles.muted}>not reported</span>
                              ) : (
                                text
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className={queryStyles.rowActions}>
              <Button
                type="button"
                variant="secondary"
                disabled={cursorStack.length === 0 || running}
                onClick={() => {
                  const stack = [...cursorStack];
                  const previous = stack.pop() ?? null;
                  void run(previous, stack);
                }}
              >
                Previous page
              </Button>
              <Button
                type="button"
                variant="secondary"
                disabled={page.next_cursor === null || running}
                onClick={() => {
                  const stack = cursor ? [...cursorStack, cursor] : [...cursorStack];
                  void run(page.next_cursor, stack);
                }}
              >
                Next page
              </Button>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
