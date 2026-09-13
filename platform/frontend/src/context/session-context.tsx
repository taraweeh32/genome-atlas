"use client";

/**
 * Session context.
 *
 * The frontend holds no credential and no session token: the session is an
 * HttpOnly cookie the browser sends automatically, and the *only* way to learn
 * whether it is valid is to ask the backend (`GET /me`). This context therefore
 * mirrors a backend answer; it never derives, caches or invents an identity.
 *
 * `capabilities` are advisory rendering hints produced by the backend. `can()`
 * hides controls a caller cannot use; it is never a security control, because
 * every request is authorized again server-side.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiClient, ApiError } from "@/lib/api-client";
import type { IdentityResponse } from "@/lib/identity-types";

export type SessionStatus = "unknown" | "loading" | "authenticated" | "anonymous" | "error";

export interface SessionState {
  readonly status: SessionStatus;
  readonly identity: IdentityResponse | null;
  readonly error: string | null;
  readonly correlationId: string | null;
}

export interface SessionContextValue extends SessionState {
  /** Re-reads the identity from the backend. */
  refresh(): Promise<void>;
  signIn(email: string, password: string): Promise<void>;
  signOut(allSessions?: boolean): Promise<void>;
  /** Advisory: whether the backend listed this platform capability. */
  can(permission: string): boolean;
  hasPlatformRole(role: string): boolean;
}

export const INITIAL_SESSION_STATE: SessionState = {
  status: "unknown",
  identity: null,
  error: null,
  correlationId: null,
};

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({
  children,
  client,
  initialState = INITIAL_SESSION_STATE,
  loadOnMount = true,
}: {
  children: ReactNode;
  client?: ApiClient;
  initialState?: SessionState;
  loadOnMount?: boolean;
}) {
  const [state, setState] = useState<SessionState>(initialState);
  const clientRef = useRef<ApiClient | null>(client ?? null);

  const resolveClient = useCallback((): ApiClient => {
    if (!clientRef.current) {
      clientRef.current = new ApiClient();
    }
    return clientRef.current;
  }, []);

  const refresh = useCallback(async () => {
    setState((current) => ({ ...current, status: "loading", error: null }));
    try {
      const identity = await resolveClient().identity();
      setState({ status: "authenticated", identity, error: null, correlationId: null });
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        // Not signed in is a normal state, not an error.
        setState({ status: "anonymous", identity: null, error: null, correlationId: null });
        return;
      }
      const error = cause instanceof ApiError ? cause : null;
      setState({
        status: "error",
        identity: null,
        error: error?.message ?? "The platform API could not be reached.",
        correlationId: error?.correlationId ?? null,
      });
    }
  }, [resolveClient]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      // Failures propagate to the caller so the form can render them; the
      // backend's uniform message is shown verbatim, never reinterpreted.
      const identity = await resolveClient().signIn(email, password);
      setState({ status: "authenticated", identity, error: null, correlationId: null });
    },
    [resolveClient],
  );

  const signOut = useCallback(
    async (allSessions = false) => {
      try {
        // The backend revokes the server-side session; that is the authoritative
        // step. A failure here is deliberately not propagated: the caller must
        // still end up signed out locally, and the revoked-or-not session is
        // re-checked on the next request either way.
        await resolveClient().signOut(allSessions);
      } catch {
        // Intentionally ignored; local state is cleared below regardless.
      } finally {
        // Whatever the backend answered, the client keeps no identity.
        setState({ status: "anonymous", identity: null, error: null, correlationId: null });
      }
    },
    [resolveClient],
  );

  useEffect(() => {
    if (loadOnMount && state.status === "unknown") {
      void refresh();
    }
    // Runs once for the initial resolution.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadOnMount]);

  const can = useCallback(
    (permission: string) => Boolean(state.identity?.capabilities.includes(permission)),
    [state.identity],
  );

  const hasPlatformRole = useCallback(
    (role: string) => Boolean(state.identity?.platform_roles.includes(role)),
    [state.identity],
  );

  const value = useMemo<SessionContextValue>(
    () => ({ ...state, refresh, signIn, signOut, can, hasPlatformRole }),
    [state, refresh, signIn, signOut, can, hasPlatformRole],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error("useSession must be used inside a SessionProvider");
  }
  return value;
}
