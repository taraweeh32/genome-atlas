import { describe, expect, it } from "vitest";
import {
  ADMINISTRATION_NAVIGATION,
  APPLICATION_NAVIGATION,
  isActive,
} from "@/components/shell/navigation";

describe("navigation model", () => {
  it("keeps the application and administration namespaces separate", () => {
    expect(APPLICATION_NAVIGATION.every((item) => item.namespace === "application")).toBe(true);
    expect(ADMINISTRATION_NAVIGATION.every((item) => item.namespace === "administration")).toBe(
      true,
    );
    expect(ADMINISTRATION_NAVIGATION.every((item) => item.href.startsWith("/admin"))).toBe(true);
  });

  it("declares a server-enforced permission for every administration entry", () => {
    expect(ADMINISTRATION_NAVIGATION.every((item) => item.requiredPermission !== null)).toBe(true);
  });

  it("marks unimplemented modules unavailable instead of linking to fake pages", () => {
    const available = [...APPLICATION_NAVIGATION, ...ADMINISTRATION_NAVIGATION].filter(
      (item) => item.available,
    );
    // Identity/tenancy, dataset, analysis, job, result, variant, filtering and
    // prioritization surfaces are implemented and reachable; the remaining
    // scientific modules stay unavailable rather than linking to empty pages.
    expect(available.map((item) => item.href).sort()).toEqual([
      "/admin",
      "/admin/annotation",
      "/admin/query",
      "/analyses",
      "/dashboard",
      "/datasets",
      "/jobs",
      "/organizations",
      "/projects",
      "/query-library",
      "/results",
      "/variant-query",
      "/variants",
    ]);
  });

  it("resolves active sections without matching sibling prefixes", () => {
    const projects = APPLICATION_NAVIGATION.find((item) => item.id === "projects")!;
    expect(isActive(projects, "/projects")).toBe(true);
    expect(isActive(projects, "/projects/prj_1")).toBe(true);
    expect(isActive(projects, "/projects-archive")).toBe(false);

    const adminOverview = ADMINISTRATION_NAVIGATION.find((item) => item.id === "admin-overview")!;
    expect(isActive(adminOverview, "/admin")).toBe(true);
    expect(isActive(adminOverview, "/admin/users")).toBe(false);
  });
});
