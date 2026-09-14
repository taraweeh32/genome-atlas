import { describe, expect, it } from "vitest";
import {
  countConditions,
  emptyGroup,
  newCondition,
  toPayload,
  valueArity,
  type DraftGroup,
} from "@/components/query/filter-builder";
import {
  emptyRanking,
  newRankingComponent,
  toRankingPayload,
} from "@/components/query/ranking-controls";
import type { FilterFieldResponse } from "@/lib/query-types";

function field(
  id: string,
  dataType: string,
  operators: readonly string[],
): FilterFieldResponse {
  return {
    id,
    label: id,
    description: "",
    data_type: dataType,
    category: "variant_identity",
    origin: "imported",
    supported_operators: operators,
    nullable: true,
    missing_semantics: ["missing"],
    allowed_values: null,
    high_cardinality: false,
    searchable: false,
    sortable: true,
    filterable: true,
    scientific_category: null,
    requires_context: ["result_set"],
    version: "1.0.0",
    available: true,
  };
}

const fields = new Map<string, FilterFieldResponse>([
  ["position", field("position", "genomic_position", ["equals", "between", "is_missing"])],
  ["gene_symbol", field("gene_symbol", "categorical", ["in", "equals"])],
  ["allele_frequency", field("allele_frequency", "decimal", ["less_than"])],
]);

describe("filter builder payload construction", () => {
  it("gives presence operators no value at all", () => {
    expect(valueArity("is_missing")).toBe("none");
    expect(valueArity("is_present")).toBe("none");
    expect(valueArity("between")).toBe("range");
    expect(valueArity("in")).toBe("list");
    expect(valueArity("equals")).toBe("single");
  });

  it("emits a structured tree, never text or an expression language", () => {
    const root: DraftGroup = {
      ...emptyGroup("and"),
      children: [
        { ...newCondition(fields.get("position")), operator: "equals", values: ["117559590"] },
        {
          ...emptyGroup("or"),
          children: [
            {
              ...newCondition(fields.get("gene_symbol")),
              operator: "in",
              values: ["CFTR", "ABCA4"],
            },
          ],
        },
      ],
    };

    const payload = toPayload(root, fields);
    expect(payload).toEqual({
      kind: "group",
      operator: "and",
      children: [
        {
          kind: "condition",
          field_id: "position",
          operator: "equals",
          // A genomic position is sent as a number, not as a string: the field's
          // declared data type decides, never a guess about the text.
          values: [117559590],
          negated: false,
        },
        {
          kind: "group",
          operator: "or",
          children: [
            {
              kind: "condition",
              field_id: "gene_symbol",
              operator: "in",
              values: ["CFTR", "ABCA4"],
              negated: false,
            },
          ],
        },
      ],
    });
    expect(countConditions(root)).toBe(2);
  });

  it("sends no value with a presence test even when one was typed earlier", () => {
    const root: DraftGroup = {
      ...emptyGroup("and"),
      children: [
        {
          ...newCondition(fields.get("position")),
          operator: "is_missing",
          values: ["117559590"],
        },
      ],
    };

    const payload = toPayload(root, fields);
    expect(payload).toEqual({
      kind: "group",
      operator: "and",
      children: [
        {
          kind: "condition",
          field_id: "position",
          operator: "is_missing",
          values: [],
          negated: false,
        },
      ],
    });
  });

  it("treats an empty filter as no filter rather than a filter that matches all", () => {
    expect(toPayload(emptyGroup("and"), fields)).toBeNull();
    expect(
      toPayload(
        { ...emptyGroup("and"), children: [emptyGroup("or")] },
        fields,
      ),
    ).toBeNull();
  });

  it("keeps a non-numeric value verbatim so the server reports the type error", () => {
    const root: DraftGroup = {
      ...emptyGroup("and"),
      children: [
        {
          ...newCondition(fields.get("allele_frequency")),
          operator: "less_than",
          values: ["rare"],
        },
      ],
    };

    const payload = toPayload(root, fields);
    expect(payload).toMatchObject({
      children: [{ values: ["rare"] }],
    });
  });
});

describe("prioritization payload construction", () => {
  it("sends no ranking when nothing is configured", () => {
    expect(toRankingPayload(emptyRanking(undefined))).toBeNull();
  });

  it("carries the method, its version, weights and the direction", () => {
    const payload = toRankingPayload({
      methodId: "weighted_field_score",
      methodVersion: "1.0.0",
      direction: "descending",
      components: [
        {
          ...newRankingComponent("allele_frequency"),
          kind: "numeric_ascending",
          weight: "0.4",
          scaleMin: "0",
          scaleMax: "0.01",
        },
      ],
    });

    expect(payload).toEqual({
      method_id: "weighted_field_score",
      method_version: "1.0.0",
      direction: "descending",
      components: [
        {
          field_id: "allele_frequency",
          kind: "numeric_ascending",
          weight: 0.4,
          scale_min: 0,
          scale_max: 0.01,
          missing_behaviour: "exclude",
        },
      ],
    });
  });

  it("omits an unnamed component instead of scoring an unnamed field", () => {
    expect(
      toRankingPayload({
        methodId: "weighted_field_score",
        methodVersion: "1.0.0",
        direction: "descending",
        components: [newRankingComponent("")],
      }),
    ).toBeNull();
  });
});
