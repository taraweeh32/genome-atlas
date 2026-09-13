/**
 * Navigation model.
 *
 * Navigation is declared as data so later packages add sections without editing
 * shell markup. `requiredPermission` is a *hint for rendering only*: the backend
 * remains the sole authority for authorization, and every navigated route
 * re-checks server-side. Items whose module is not implemented yet are marked
 * `available: false` so the shell never pretends a feature exists.
 */

export type NavigationNamespace = "application" | "administration";

export interface NavigationItem {
  readonly id: string;
  readonly label: string;
  readonly href: string;
  readonly namespace: NavigationNamespace;
  /** Server-enforced permission this section will require. */
  readonly requiredPermission: string | null;
  /** False until the owning package is implemented. */
  readonly available: boolean;
}

export const APPLICATION_NAVIGATION: readonly NavigationItem[] = [
  {
    id: "dashboard",
    label: "Dashboard",
    href: "/dashboard",
    namespace: "application",
    requiredPermission: null,
    available: true,
  },
  {
    id: "organizations",
    label: "Organizations",
    href: "/organizations",
    namespace: "application",
    requiredPermission: null,
    available: true,
  },
  {
    id: "projects",
    label: "Projects",
    href: "/projects",
    namespace: "application",
    requiredPermission: "project.read",
    available: true,
  },
  {
    id: "datasets",
    label: "Datasets",
    href: "/datasets",
    namespace: "application",
    requiredPermission: "dataset.read",
    available: true,
  },
  {
    id: "analyses",
    label: "Analyses",
    href: "/analyses",
    namespace: "application",
    requiredPermission: "analysis.read",
    available: false,
  },
  {
    id: "variants",
    label: "Variant review",
    href: "/variants",
    namespace: "application",
    requiredPermission: "variant.read",
    available: false,
  },
  {
    id: "reports",
    label: "Reports",
    href: "/reports",
    namespace: "application",
    requiredPermission: "report.read",
    available: false,
  },
];

export const ADMINISTRATION_NAVIGATION: readonly NavigationItem[] = [
  {
    id: "admin-overview",
    label: "Overview",
    href: "/admin",
    namespace: "administration",
    requiredPermission: "platform.administer",
    available: true,
  },
  {
    id: "admin-users",
    label: "Users",
    href: "/admin/users",
    namespace: "administration",
    requiredPermission: "platform.user.manage",
    available: false,
  },
  {
    id: "admin-organizations",
    label: "Organizations",
    href: "/admin/organizations",
    namespace: "administration",
    requiredPermission: "platform.organization.manage",
    available: false,
  },
  {
    id: "admin-compute",
    label: "Scientific compute",
    href: "/admin/compute",
    namespace: "administration",
    requiredPermission: "platform.compute.manage",
    available: false,
  },
  {
    id: "admin-audit",
    label: "Audit",
    href: "/admin/audit",
    namespace: "administration",
    requiredPermission: "platform.audit.read",
    available: false,
  },
];

/** True when `pathname` is inside the item's section. */
export function isActive(item: NavigationItem, pathname: string): boolean {
  if (item.href === "/admin") {
    return pathname === "/admin";
  }
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}
