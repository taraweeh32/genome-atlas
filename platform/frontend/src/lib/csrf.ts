/**
 * CSRF double-submit support.
 *
 * The backend issues two cookies on sign-in: an HttpOnly session cookie the
 * browser sends automatically and never exposes to script, and a readable CSRF
 * cookie whose value must be echoed in a header on every unsafe request. Reading
 * this cookie is not an authentication check — the session itself is unreadable
 * here by design.
 */

export const CSRF_COOKIE_NAME = "gp_csrf";
export const CSRF_HEADER_NAME = "X-CSRF-Token";

export function readCookie(name: string, cookieString?: string): string | null {
  const source = cookieString ?? (typeof document === "undefined" ? "" : document.cookie);
  for (const part of source.split(";")) {
    const separator = part.indexOf("=");
    if (separator === -1) continue;
    if (part.slice(0, separator).trim() === name) {
      return decodeURIComponent(part.slice(separator + 1).trim());
    }
  }
  return null;
}

export function readCsrfToken(cookieString?: string): string | null {
  return readCookie(CSRF_COOKIE_NAME, cookieString);
}
