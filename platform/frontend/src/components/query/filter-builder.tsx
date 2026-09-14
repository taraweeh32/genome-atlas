"use client";

/**
 * The filter builder: a structured editor for a filter expression tree.
 *
 * Four properties are deliberate:
 *
 * - **Nobody writes JSON.** The user picks a field, an operator and values.
 *   Groups nest, combine with AND/OR/NOT, and can be added, duplicated or
 *   removed. The payload is assembled from the tree, never typed.
 * - **Operators are type-aware.** The operator list for a condition is the list
 *   the server published for that field; the builder never offers an operator
 *   the field does not support, and never invents one.
 * - **Missing is not empty, zero or false.** The builder offers the presence
 *   operators as first-class choices and never rewrites a value into a
 *   presence test (or the reverse).
 * - **Validation belongs to the server.** Issues arrive keyed by tree path and
 *   are rendered against the condition they concern. Nothing is repaired here.
 *
 * High-cardinality fields (genes, transcripts, sample and external identifiers)
 * are searched through the bounded server endpoint. The browser never asks for a
 * complete distinct-value list, and a truncated response says so.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { getApiClient } from "@/lib/api-client";
import type {
  FilterConditionPayload,
  FilterFieldResponse,
  FilterGroupPayload,
  FilterLogicalOperator,
  FilterNodePayload,
  FilterValidationIssueResponse,
} from "@/lib/query-types";
import styles from "./query.module.css";

/** Operators that test presence or shape and therefore take no value. */
const NO_VALUE_OPERATORS = new Set([
  "is_missing",
  "is_present",
  "is_empty",
  "is_not_empty",
  "is_true",
  "is_false",
]);

/** Operators bounded by two endpoints. */
const RANGE_OPERATORS = new Set(["between", "not_between", "within_range"]);

/** Operators taking an explicit list of values. */
const LIST_OPERATORS = new Set(["in", "not_in"]);

const NUMERIC_TYPES = new Set(["integer", "decimal", "genomic_position"]);

export type ValueArity = "none" | "single" | "range" | "list";

export function valueArity(operator: string): ValueArity {
  if (NO_VALUE_OPERATORS.has(operator)) return "none";
  if (RANGE_OPERATORS.has(operator)) return "range";
  if (LIST_OPERATORS.has(operator)) return "list";
  return "single";
}

let sequence = 0;
const nextKey = () => `n${(sequence += 1)}`;

/** A condition being edited. Values are kept as text and coerced on submit. */
export interface DraftCondition {
  readonly key: string;
  readonly kind: "condition";
  readonly fieldId: string;
  readonly operator: string;
  readonly values: readonly string[];
  readonly negated: boolean;
}

export interface DraftGroup {
  readonly key: string;
  readonly kind: "group";
  readonly operator: FilterLogicalOperator;
  readonly children: readonly DraftNode[];
}

export type DraftNode = DraftCondition | DraftGroup;

export function emptyGroup(operator: FilterLogicalOperator = "and"): DraftGroup {
  return { key: nextKey(), kind: "group", operator, children: [] };
}

export function newCondition(field: FilterFieldResponse | undefined): DraftCondition {
  return {
    key: nextKey(),
    kind: "condition",
    fieldId: field?.id ?? "",
    operator: field?.supported_operators[0] ?? "equals",
    values: [""],
    negated: false,
  };
}

function coerce(field: FilterFieldResponse | undefined, raw: string): unknown {
  const text = raw.trim();
  if (field && NUMERIC_TYPES.has(field.data_type)) {
    const parsed = Number(text);
    // A value that is not a number is sent unchanged: the server reports the
    // type error against this condition rather than the builder guessing.
    return Number.isFinite(parsed) && text !== "" ? parsed : text;
  }
  if (field?.data_type === "boolean") {
    if (text === "true") return true;
    if (text === "false") return false;
  }
  return text;
}

/** Builds the wire payload. Empty groups are dropped, nothing else is altered. */
export function toPayload(
  node: DraftNode,
  fields: ReadonlyMap<string, FilterFieldResponse>,
): FilterNodePayload | null {
  if (node.kind === "condition") {
    if (!node.fieldId) return null;
    const field = fields.get(node.fieldId);
    const arity = valueArity(node.operator);
    const raw = arity === "none" ? [] : node.values.filter((value) => value.trim() !== "");
    const condition: FilterConditionPayload = {
      kind: "condition",
      field_id: node.fieldId,
      operator: node.operator,
      values: raw.map((value) => coerce(field, value)),
      negated: node.negated,
    };
    return condition;
  }
  const children = node.children
    .map((child) => toPayload(child, fields))
    .filter((child): child is FilterNodePayload => child !== null);
  if (children.length === 0) return null;
  return { kind: "group", operator: node.operator, children };
}

export function countConditions(node: DraftNode): number {
  return node.kind === "condition"
    ? 1
    : node.children.reduce((total, child) => total + countConditions(child), 0);
}

function mapNode(
  node: DraftNode,
  key: string,
  change: (node: DraftNode) => DraftNode | null,
): DraftNode | null {
  if (node.key === key) return change(node);
  if (node.kind !== "group") return node;
  const children = node.children
    .map((child) => mapNode(child, key, change))
    .filter((child): child is DraftNode => child !== null);
  return { ...node, children };
}

function cloneNode(node: DraftNode): DraftNode {
  return node.kind === "condition"
    ? { ...node, key: nextKey() }
    : { ...node, key: nextKey(), children: node.children.map(cloneNode) };
}

interface BuilderProps {
  readonly root: DraftGroup;
  readonly fields: readonly FilterFieldResponse[];
  readonly issues: readonly FilterValidationIssueResponse[];
  readonly resultSetId: string | null;
  readonly disabled?: boolean;
  readonly onChange: (root: DraftGroup) => void;
}

export function FilterBuilder({
  root,
  fields,
  issues,
  resultSetId,
  disabled = false,
  onChange,
}: BuilderProps) {
  const byId = useMemo(
    () => new Map(fields.map((field) => [field.id, field] as const)),
    [fields],
  );

  const update = useCallback(
    (key: string, change: (node: DraftNode) => DraftNode | null) => {
      const next = mapNode(root, key, change);
      if (next && next.kind === "group") onChange(next);
      else onChange(emptyGroup(root.operator));
    },
    [onChange, root],
  );

  return (
    <div className={styles.builder}>
      <GroupEditor
        node={root}
        path="filter"
        depth={0}
        fields={fields}
        byId={byId}
        issues={issues}
        resultSetId={resultSetId}
        disabled={disabled}
        isRoot
        update={update}
      />
    </div>
  );
}

interface NodeProps {
  readonly path: string;
  readonly depth: number;
  readonly fields: readonly FilterFieldResponse[];
  readonly byId: ReadonlyMap<string, FilterFieldResponse>;
  readonly issues: readonly FilterValidationIssueResponse[];
  readonly resultSetId: string | null;
  readonly disabled: boolean;
  readonly update: (key: string, change: (node: DraftNode) => DraftNode | null) => void;
}

function GroupEditor({
  node,
  isRoot = false,
  ...rest
}: NodeProps & { readonly node: DraftGroup; readonly isRoot?: boolean }) {
  const { fields, byId, issues, resultSetId, disabled, update, path, depth } = rest;
  const ownIssues = issues.filter((issue) => issue.path === path);

  const addCondition = () =>
    update(node.key, (current) =>
      current.kind === "group"
        ? { ...current, children: [...current.children, newCondition(fields[0])] }
        : current,
    );

  const addGroup = () =>
    update(node.key, (current) =>
      current.kind === "group"
        ? { ...current, children: [...current.children, emptyGroup("or")] }
        : current,
    );

  return (
    <div className={styles.group}>
      <div className={styles.groupHeader}>
        <span className={styles.groupLabel}>{isRoot ? "Filter" : "Group"}</span>
        <label className={styles.control}>
          <span className={styles.controlLabel}>Combine with</span>
          <select
            className={styles.select}
            value={node.operator}
            disabled={disabled}
            aria-label="Group logical operator"
            onChange={(event) =>
              update(node.key, (current) =>
                current.kind === "group"
                  ? {
                      ...current,
                      operator: event.target.value as FilterLogicalOperator,
                    }
                  : current,
              )
            }
          >
            <option value="and">All of (AND)</option>
            <option value="or">Any of (OR)</option>
            <option value="not">Not (NOT)</option>
          </select>
        </label>
        <div className={styles.rowActions}>
          <Button
            type="button"
            variant="secondary"
            onClick={addCondition}
            disabled={disabled}
          >
            Add condition
          </Button>
          <Button type="button" variant="secondary" onClick={addGroup} disabled={disabled}>
            Add group
          </Button>
          {!isRoot ? (
            <>
              <Button
                type="button"
                variant="secondary"
                onClick={() => update(node.key, (current) => cloneNode(current))}
                disabled={disabled}
              >
                Duplicate
              </Button>
              <Button
                type="button"
                variant="danger"
                onClick={() => update(node.key, () => null)}
                disabled={disabled}
              >
                Remove
              </Button>
            </>
          ) : null}
        </div>
      </div>
      {node.operator === "not" && node.children.length !== 1 ? (
        <p className={styles.hint}>
          A NOT group negates exactly one condition or group.
        </p>
      ) : null}
      {ownIssues.map((issue) => (
        <p key={`${issue.path}-${issue.message}`} className={styles.issue}>
          {issue.message}
        </p>
      ))}
      <div className={styles.children}>
        {node.children.length === 0 ? (
          <p className={styles.hint}>
            No conditions yet. An empty filter returns the whole result set,
            page by page.
          </p>
        ) : null}
        {node.children.map((child, index) =>
          child.kind === "group" ? (
            <GroupEditor
              key={child.key}
              node={child}
              path={`${path}.children[${index}]`}
              depth={depth + 1}
              fields={fields}
              byId={byId}
              issues={issues}
              resultSetId={resultSetId}
              disabled={disabled}
              update={update}
            />
          ) : (
            <ConditionEditor
              key={child.key}
              node={child}
              path={`${path}.children[${index}]`}
              depth={depth + 1}
              fields={fields}
              byId={byId}
              issues={issues}
              resultSetId={resultSetId}
              disabled={disabled}
              update={update}
            />
          ),
        )}
      </div>
    </div>
  );
}

function ConditionEditor({
  node,
  path,
  fields,
  byId,
  issues,
  resultSetId,
  disabled,
  update,
}: NodeProps & { readonly node: DraftCondition }) {
  const field = byId.get(node.fieldId);
  const arity = valueArity(node.operator);
  const ownIssues = issues.filter((issue) => issue.path === path);

  const setValues = (values: readonly string[]) =>
    update(node.key, (current) =>
      current.kind === "condition" ? { ...current, values } : current,
    );

  const changeField = (fieldId: string) => {
    const next = byId.get(fieldId);
    update(node.key, (current) =>
      current.kind === "condition"
        ? {
            ...current,
            fieldId,
            // The operator is reset rather than carried over: an operator that
            // one type supports is not necessarily valid for another.
            operator: next?.supported_operators.includes(current.operator)
              ? current.operator
              : (next?.supported_operators[0] ?? "equals"),
            values: [""],
          }
        : current,
    );
  };

  return (
    <div className={styles.condition}>
      <label className={`${styles.control} ${styles.controlWide}`}>
        <span className={styles.controlLabel}>Field</span>
        <select
          className={styles.select}
          value={node.fieldId}
          disabled={disabled}
          onChange={(event) => changeField(event.target.value)}
        >
          <option value="">Select a field…</option>
          {fields.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label} — {option.category}
            </option>
          ))}
        </select>
      </label>

      <label className={styles.control}>
        <span className={styles.controlLabel}>Operator</span>
        <select
          className={styles.select}
          value={node.operator}
          disabled={disabled || !field}
          onChange={(event) =>
            update(node.key, (current) =>
              current.kind === "condition"
                ? { ...current, operator: event.target.value, values: [""] }
                : current,
            )
          }
        >
          {(field?.supported_operators ?? [node.operator]).map((operator) => (
            <option key={operator} value={operator}>
              {operator.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </label>

      {arity === "none" ? (
        <p className={styles.hint}>
          This operator tests whether the data reports a value; it takes no value
          of its own.
        </p>
      ) : null}

      {arity === "single" ? (
        <ValueField
          label="Value"
          field={field}
          value={node.values[0] ?? ""}
          resultSetId={resultSetId}
          disabled={disabled}
          onChange={(value) => setValues([value])}
        />
      ) : null}

      {arity === "range" ? (
        <>
          <ValueField
            label="From"
            field={field}
            value={node.values[0] ?? ""}
            resultSetId={resultSetId}
            disabled={disabled}
            onChange={(value) => setValues([value, node.values[1] ?? ""])}
          />
          <ValueField
            label="To"
            field={field}
            value={node.values[1] ?? ""}
            resultSetId={resultSetId}
            disabled={disabled}
            onChange={(value) => setValues([node.values[0] ?? "", value])}
          />
        </>
      ) : null}

      {arity === "list" ? (
        <ListValueField
          field={field}
          values={node.values}
          resultSetId={resultSetId}
          disabled={disabled}
          onChange={setValues}
        />
      ) : null}

      <label className={styles.checkbox}>
        <input
          type="checkbox"
          checked={node.negated}
          disabled={disabled}
          onChange={(event) =>
            update(node.key, (current) =>
              current.kind === "condition"
                ? { ...current, negated: event.target.checked }
                : current,
            )
          }
        />
        Negate
      </label>

      <div className={styles.rowActions}>
        <Button
          type="button"
          variant="secondary"
          onClick={() => update(node.key, (current) => cloneNode(current))}
          disabled={disabled}
        >
          Duplicate
        </Button>
        <Button
          type="button"
          variant="danger"
          onClick={() => update(node.key, () => null)}
          disabled={disabled}
        >
          Remove
        </Button>
      </div>

      {ownIssues.map((issue) => (
        <p key={`${issue.path}-${issue.message}`} className={styles.issue}>
          {issue.message}
        </p>
      ))}
    </div>
  );
}

/**
 * Bounded server-side value search for one field.
 *
 * The request is only made for a field the server marked searchable, and only
 * when a result set is in context: distinct values are data, and reading them
 * requires the same authorization as reading the rows.
 */
function useValueSearch(
  field: FilterFieldResponse | undefined,
  resultSetId: string | null,
  term: string,
) {
  const [values, setValues] = useState<readonly string[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [failed, setFailed] = useState(false);
  const latest = useRef(0);

  useEffect(() => {
    if (!field?.searchable || !resultSetId || term.trim().length < 2) {
      setValues([]);
      setTruncated(false);
      setFailed(false);
      return;
    }
    const ticket = (latest.current += 1);
    const timer = setTimeout(() => {
      void getApiClient()
        .filterFieldValues(field.id, {
          result_set_id: resultSetId,
          search: term.trim(),
          limit: 20,
        })
        .then((response) => {
          if (ticket !== latest.current) return;
          setValues(response.values.map((entry) => String(entry.value)));
          setTruncated(response.truncated);
          setFailed(false);
        })
        .catch(() => {
          if (ticket !== latest.current) return;
          setValues([]);
          setTruncated(false);
          setFailed(true);
        });
    }, 250);
    return () => clearTimeout(timer);
  }, [field?.id, field?.searchable, resultSetId, term]);

  return { values, truncated, failed };
}

function ValueField({
  label,
  field,
  value,
  resultSetId,
  disabled,
  onChange,
}: {
  readonly label: string;
  readonly field: FilterFieldResponse | undefined;
  readonly value: string;
  readonly resultSetId: string | null;
  readonly disabled: boolean;
  readonly onChange: (value: string) => void;
}) {
  const { values, truncated, failed } = useValueSearch(field, resultSetId, value);
  const allowed = field?.allowed_values ?? null;

  return (
    <div className={`${styles.control} ${styles.controlWide}`}>
      <span className={styles.controlLabel}>{label}</span>
      {allowed ? (
        <select
          className={styles.select}
          value={value}
          disabled={disabled}
          aria-label={label}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">Select…</option>
          {allowed.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : (
        <input
          className={styles.input}
          value={value}
          disabled={disabled}
          aria-label={label}
          inputMode={field && NUMERIC_TYPES.has(field.data_type) ? "decimal" : "text"}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      {values.length > 0 ? (
        <div className={styles.suggestions}>
          {values.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              className={styles.suggestion}
              onClick={() => onChange(suggestion)}
            >
              {suggestion}
            </button>
          ))}
        </div>
      ) : null}
      {truncated ? (
        <p className={styles.hint}>
          More values match. Refine the search — the full list is never listed.
        </p>
      ) : null}
      {failed ? (
        <p className={styles.issue}>Value search unavailable for this field.</p>
      ) : null}
    </div>
  );
}

function ListValueField({
  field,
  values,
  resultSetId,
  disabled,
  onChange,
}: {
  readonly field: FilterFieldResponse | undefined;
  readonly values: readonly string[];
  readonly resultSetId: string | null;
  readonly disabled: boolean;
  readonly onChange: (values: readonly string[]) => void;
}) {
  const [term, setTerm] = useState("");
  const { values: suggestions, truncated, failed } = useValueSearch(
    field,
    resultSetId,
    term,
  );
  const selected = values.filter((value) => value.trim() !== "");

  const add = (value: string) => {
    const text = value.trim();
    if (text === "" || selected.includes(text)) return;
    onChange([...selected, text]);
    setTerm("");
  };

  return (
    <div className={`${styles.control} ${styles.controlWide}`}>
      <span className={styles.controlLabel}>Values</span>
      <input
        className={styles.input}
        value={term}
        disabled={disabled}
        aria-label="Add value"
        placeholder="Type a value and press Enter"
        onChange={(event) => setTerm(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            add(term);
          }
        }}
      />
      {selected.length > 0 ? (
        <div className={styles.chips}>
          {selected.map((value) => (
            <span key={value} className={styles.chip}>
              {value}
              <button
                type="button"
                aria-label={`Remove ${value}`}
                onClick={() => onChange(selected.filter((entry) => entry !== value))}
                disabled={disabled}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      ) : null}
      {suggestions.length > 0 ? (
        <div className={styles.suggestions}>
          {suggestions.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              className={styles.suggestion}
              onClick={() => add(suggestion)}
            >
              {suggestion}
            </button>
          ))}
        </div>
      ) : null}
      {truncated ? (
        <p className={styles.hint}>More values match. Refine the search.</p>
      ) : null}
      {failed ? (
        <p className={styles.issue}>Value search unavailable for this field.</p>
      ) : null}
    </div>
  );
}
