"use client";

/**
 * Ranking configuration: a prioritization score, assembled explicitly.
 *
 * Ranking is a separate abstraction from filtering. Nothing in this component
 * can change which rows are returned — it only decides the order of rows the
 * filter already admitted. That separation is enforced by the backend, and the
 * UI mirrors it by never mixing the two payloads.
 *
 * The score is a declared arithmetic combination of stored fields with visible
 * weights. It is not a pathogenicity estimate, a diagnosis, or any other
 * clinical conclusion, and this surface deliberately never labels it as one:
 * shipped methods report `scientifically_validated: false`, which is stated to
 * the user rather than hidden.
 *
 * Rows that no component could score are counted separately and ordered last in
 * either direction. "Nothing to score" is not a low priority.
 */

import { Button } from "@/components/ui/button";
import type {
  FilterFieldResponse,
  RankingComponentPayload,
  RankingConfigurationPayload,
  RankingMethodResponse,
} from "@/lib/query-types";
import styles from "./query.module.css";

/** Component kinds the shipped methods accept, with plain-language labels. */
const COMPONENT_KINDS: readonly { value: string; label: string }[] = [
  { value: "numeric_ascending", label: "Numeric — lower value scores higher" },
  { value: "numeric_descending", label: "Numeric — higher value scores higher" },
  { value: "category_priority", label: "Category priority — ordered list" },
  { value: "presence", label: "Presence — a reported value scores" },
];

export interface DraftComponent {
  readonly key: string;
  readonly fieldId: string;
  readonly kind: string;
  readonly weight: string;
  readonly scaleMin: string;
  readonly scaleMax: string;
  readonly categoryPriority: string;
  readonly missingBehaviour: string;
}

export interface DraftRanking {
  readonly methodId: string;
  readonly methodVersion: string;
  readonly direction: string;
  readonly components: readonly DraftComponent[];
}

let sequence = 0;

export function newRankingComponent(fieldId = ""): DraftComponent {
  return {
    key: `c${(sequence += 1)}`,
    fieldId,
    kind: "numeric_descending",
    weight: "1",
    scaleMin: "",
    scaleMax: "",
    categoryPriority: "",
    missingBehaviour: "unscored",
  };
}

export function emptyRanking(method: RankingMethodResponse | undefined): DraftRanking {
  return {
    methodId: method?.id ?? "",
    methodVersion: method?.version ?? "",
    direction: "descending",
    components: [],
  };
}

function optionalNumber(text: string): number | undefined {
  const value = Number(text.trim());
  return text.trim() !== "" && Number.isFinite(value) ? value : undefined;
}

/**
 * Builds the wire payload, or `null` when no ranking is configured.
 *
 * An unconfigured ranking is sent as *no ranking at all*, never as a neutral
 * one: "no ranking" and "a ranking that changes nothing" are recorded
 * differently in the execution record.
 */
export function toRankingPayload(draft: DraftRanking): RankingConfigurationPayload | null {
  if (!draft.methodId || draft.components.length === 0) return null;
  const components: RankingComponentPayload[] = draft.components
    .filter((component) => component.fieldId !== "")
    .map((component) => {
      const priority = component.categoryPriority
        .split(",")
        .map((entry) => entry.trim())
        .filter((entry) => entry !== "");
      return {
        field_id: component.fieldId,
        kind: component.kind,
        weight: Number(component.weight) || 0,
        ...(optionalNumber(component.scaleMin) !== undefined
          ? { scale_min: optionalNumber(component.scaleMin) }
          : {}),
        ...(optionalNumber(component.scaleMax) !== undefined
          ? { scale_max: optionalNumber(component.scaleMax) }
          : {}),
        ...(priority.length > 0 ? { category_priority: priority } : {}),
        missing_behaviour: component.missingBehaviour,
      };
    });
  if (components.length === 0) return null;
  return {
    method_id: draft.methodId,
    method_version: draft.methodVersion,
    components,
    direction: draft.direction,
  };
}

interface Props {
  readonly draft: DraftRanking;
  readonly methods: readonly RankingMethodResponse[];
  readonly fields: readonly FilterFieldResponse[];
  readonly disabled?: boolean;
  readonly onChange: (draft: DraftRanking) => void;
}

export function RankingControls({
  draft,
  methods,
  fields,
  disabled = false,
  onChange,
}: Props) {
  const method = methods.find((candidate) => candidate.id === draft.methodId);
  const sortable = fields.filter((field) => field.sortable);

  const setComponent = (key: string, change: Partial<DraftComponent>) =>
    onChange({
      ...draft,
      components: draft.components.map((component) =>
        component.key === key ? { ...component, ...change } : component,
      ),
    });

  return (
    <div className={styles.builder}>
      <div className={styles.groupHeader}>
        <label className={`${styles.control} ${styles.controlWide}`}>
          <span className={styles.controlLabel}>Prioritization method</span>
          <select
            className={styles.select}
            value={draft.methodId}
            disabled={disabled}
            onChange={(event) => {
              const next = methods.find(
                (candidate) => candidate.id === event.target.value,
              );
              onChange({
                ...draft,
                methodId: next?.id ?? "",
                methodVersion: next?.version ?? "",
              });
            }}
          >
            <option value="">No prioritization (stable default order)</option>
            {methods.map((candidate) => (
              <option
                key={candidate.id}
                value={candidate.id}
                disabled={!candidate.available}
              >
                {candidate.name} (v{candidate.version})
              </option>
            ))}
          </select>
        </label>

        <label className={styles.control}>
          <span className={styles.controlLabel}>Order</span>
          <select
            className={styles.select}
            value={draft.direction}
            disabled={disabled || !draft.methodId}
            onChange={(event) => onChange({ ...draft, direction: event.target.value })}
          >
            <option value="descending">Highest score first</option>
            <option value="ascending">Lowest score first</option>
          </select>
        </label>

        <div className={styles.rowActions}>
          <Button
            type="button"
            variant="secondary"
            disabled={disabled || !draft.methodId}
            onClick={() =>
              onChange({
                ...draft,
                components: [
                  ...draft.components,
                  newRankingComponent(sortable[0]?.id ?? ""),
                ],
              })
            }
          >
            Add component
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={disabled}
            onClick={() => onChange(emptyRanking(undefined))}
          >
            Reset
          </Button>
        </div>
      </div>

      {method ? (
        <>
          <p className={styles.hint}>{method.description}</p>
          <p className={styles.hint}>
            This score is a prioritization order over recorded values, not a
            clinical assessment.{" "}
            {method.scientifically_validated
              ? "This method carries a separate scientific validation."
              : "It has not been scientifically validated as a clinical measure."}{" "}
            Rows with no value to score are listed last and counted separately.
          </p>
        </>
      ) : (
        <p className={styles.hint}>
          Without a prioritization method, rows are returned in the platform&apos;s
          stable default order.
        </p>
      )}

      <div className={styles.components}>
        {draft.components.map((component) => (
          <div key={component.key} className={styles.condition}>
            <label className={`${styles.control} ${styles.controlWide}`}>
              <span className={styles.controlLabel}>Field</span>
              <select
                className={styles.select}
                value={component.fieldId}
                disabled={disabled}
                onChange={(event) =>
                  setComponent(component.key, { fieldId: event.target.value })
                }
              >
                <option value="">Select a field…</option>
                {sortable.map((field) => (
                  <option key={field.id} value={field.id}>
                    {field.label} — {field.category}
                  </option>
                ))}
              </select>
            </label>

            <label className={styles.control}>
              <span className={styles.controlLabel}>Contribution</span>
              <select
                className={styles.select}
                value={component.kind}
                disabled={disabled}
                onChange={(event) =>
                  setComponent(component.key, { kind: event.target.value })
                }
              >
                {COMPONENT_KINDS.filter(
                  (kind) =>
                    !method || method.supported_component_kinds.includes(kind.value),
                ).map((kind) => (
                  <option key={kind.value} value={kind.value}>
                    {kind.label}
                  </option>
                ))}
              </select>
            </label>

            <label className={styles.control}>
              <span className={styles.controlLabel}>Weight</span>
              <input
                className={styles.input}
                value={component.weight}
                inputMode="decimal"
                disabled={disabled}
                onChange={(event) =>
                  setComponent(component.key, { weight: event.target.value })
                }
              />
            </label>

            {component.kind.startsWith("numeric") ? (
              <>
                <label className={styles.control}>
                  <span className={styles.controlLabel}>Scale from</span>
                  <input
                    className={styles.input}
                    value={component.scaleMin}
                    inputMode="decimal"
                    disabled={disabled}
                    onChange={(event) =>
                      setComponent(component.key, { scaleMin: event.target.value })
                    }
                  />
                </label>
                <label className={styles.control}>
                  <span className={styles.controlLabel}>Scale to</span>
                  <input
                    className={styles.input}
                    value={component.scaleMax}
                    inputMode="decimal"
                    disabled={disabled}
                    onChange={(event) =>
                      setComponent(component.key, { scaleMax: event.target.value })
                    }
                  />
                </label>
              </>
            ) : null}

            {component.kind === "category_priority" ? (
              <label className={`${styles.control} ${styles.controlWide}`}>
                <span className={styles.controlLabel}>
                  Categories, highest priority first
                </span>
                <input
                  className={styles.input}
                  value={component.categoryPriority}
                  disabled={disabled}
                  placeholder="value_a, value_b, value_c"
                  onChange={(event) =>
                    setComponent(component.key, {
                      categoryPriority: event.target.value,
                    })
                  }
                />
              </label>
            ) : null}

            <label className={styles.control}>
              <span className={styles.controlLabel}>When not reported</span>
              <select
                className={styles.select}
                value={component.missingBehaviour}
                disabled={disabled}
                onChange={(event) =>
                  setComponent(component.key, { missingBehaviour: event.target.value })
                }
              >
                <option value="unscored">Leave unscored</option>
                <option value="floor">Use an explicit floor value</option>
              </select>
            </label>

            {component.missingBehaviour === "floor" ? (
              <p className={styles.hint}>
                A floor is an explicit choice recorded with the execution; it is
                not the same as the value being zero.
              </p>
            ) : null}

            <div className={styles.rowActions}>
              <Button
                type="button"
                variant="danger"
                disabled={disabled}
                onClick={() =>
                  onChange({
                    ...draft,
                    components: draft.components.filter(
                      (entry) => entry.key !== component.key,
                    ),
                  })
                }
              >
                Remove
              </Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
