/**
 * Frontend runtime configuration.
 *
 * Only non-secret, publishable values may live here. Secrets, database
 * credentials, object-storage keys and scientific service tokens exist solely in
 * backend configuration.
 */

export type AppEnvironment = "development" | "test" | "staging" | "production";

export interface FrontendConfig {
  /** Base URL of the versioned REST API, e.g. http://localhost:8000 */
  readonly apiBaseUrl: string;
  /** API version namespace the client speaks. */
  readonly apiVersion: "v1";
  readonly environment: AppEnvironment;
}

function readEnvironment(raw: string | undefined): AppEnvironment {
  switch (raw) {
    case "test":
    case "staging":
    case "production":
      return raw;
    default:
      return "development";
  }
}

export function loadFrontendConfig(
  env: Record<string, string | undefined> = process.env,
): FrontendConfig {
  const apiBaseUrl = (env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");
  if (!apiBaseUrl) {
    // Fail loudly rather than silently calling a wrong origin.
    throw new Error("NEXT_PUBLIC_API_BASE_URL is required");
  }
  return {
    apiBaseUrl,
    apiVersion: "v1",
    environment: readEnvironment(env.NEXT_PUBLIC_APP_ENVIRONMENT),
  };
}

export function apiUrl(config: FrontendConfig, path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${config.apiBaseUrl}/api/${config.apiVersion}${normalized}`;
}
