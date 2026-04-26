import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Navigate, useLocation } from "react-router-dom";
import type { Session, User } from "@supabase/supabase-js";

import { isSupabaseConfigured, supabase, SUPABASE_ENV_MISSING_MESSAGE } from "@/lib/supabase";

export type AppRole = "superadmin" | "admin" | "user";

export type AppPermissions = {
  isSuperadmin: boolean;
  canRegisterProcurements: boolean;
  canStartRuns: boolean;
  canManageCompany: boolean;
  canManageBids: boolean;
  canDeleteProcurements: boolean;
  canDeleteRuns: boolean;
  canManageTeam: boolean;
};

export type AuthContextValue = {
  session: Session | null;
  user: User | null;
  role: AppRole | null;
  organizationId: string | null;
  organizationName: string | null;
  displayName: string | null;
  loading: boolean;
  error: string | null;
  permissions: AppPermissions;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  refreshMembership: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const emptyPermissions: AppPermissions = {
  isSuperadmin: false,
  canRegisterProcurements: false,
  canStartRuns: false,
  canManageCompany: false,
  canManageBids: false,
  canDeleteProcurements: false,
  canDeleteRuns: false,
  canManageTeam: false,
};

export function permissionsForRole(role: AppRole | null): AppPermissions {
  if (role === "superadmin") {
    return {
      isSuperadmin: true,
      canRegisterProcurements: true,
      canStartRuns: true,
      canManageCompany: true,
      canManageBids: true,
      canDeleteProcurements: true,
      canDeleteRuns: true,
      canManageTeam: true,
    };
  }

  if (role === "admin") {
    return {
      isSuperadmin: false,
      canRegisterProcurements: true,
      canStartRuns: true,
      canManageCompany: true,
      canManageBids: true,
      canDeleteProcurements: true,
      canDeleteRuns: true,
      canManageTeam: true,
    };
  }

  if (role === "user") {
    return {
      isSuperadmin: false,
      canRegisterProcurements: true,
      canStartRuns: true,
      canManageCompany: false,
      canManageBids: false,
      canDeleteProcurements: false,
      canDeleteRuns: false,
      canManageTeam: false,
    };
  }

  return emptyPermissions;
}

type MembershipState = {
  role: AppRole | null;
  organizationId: string | null;
  organizationName: string | null;
  displayName: string | null;
};

const emptyMembership: MembershipState = {
  role: null,
  organizationId: null,
  organizationName: null,
  displayName: null,
};

const localMockAuthEnabled = !isSupabaseConfigured && import.meta.env.MODE !== "production";

const localDemoUser = {
  id: "local-demo-user",
  aud: "authenticated",
  email: "demo@bidded.local",
  app_metadata: { provider: "email", providers: ["email"] },
  user_metadata: { name: "Demo Operator" },
  created_at: "2026-04-01T00:00:00.000Z",
} as User;

const localDemoSession = {
  access_token: "local-demo-access-token",
  refresh_token: "local-demo-refresh-token",
  token_type: "bearer",
  expires_in: 60 * 60 * 24,
  expires_at: 1_804_000_000,
  user: localDemoUser,
} as Session;

const localDemoMembership: MembershipState = {
  role: "admin",
  organizationId: "local-demo-organization",
  organizationName: "Bidded Demo",
  displayName: "Demo Operator",
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [membership, setMembership] = useState<MembershipState>(emptyMembership);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadLocalDemoAuth = useCallback(() => {
    setSession(localDemoSession);
    setUser(localDemoUser);
    setMembership(localDemoMembership);
    setError(null);
  }, []);

  const loadMembership = useCallback(async (nextSession: Session | null) => {
    setSession(nextSession);
    setUser(nextSession?.user ?? null);
    setError(null);

    if (!nextSession?.user || !supabase) {
      setMembership(emptyMembership);
      return;
    }

    const userId = nextSession.user.id;
    const [profileRes, membershipRes] = await Promise.all([
      supabase
        .from("profiles")
        .select("global_role,display_name,email")
        .eq("user_id", userId)
        .maybeSingle(),
      supabase
        .from("organization_memberships")
        .select("organization_id,role,status,organizations(id,name,tenant_key)")
        .eq("user_id", userId)
        .eq("status", "active")
        .order("created_at", { ascending: true })
        .limit(1),
    ]);

    if (profileRes.error) {
      throw new Error(`load profile: ${profileRes.error.message}`);
    }
    if (membershipRes.error) {
      throw new Error(`load membership: ${membershipRes.error.message}`);
    }

    const profile = (profileRes.data ?? {}) as {
      global_role?: string | null;
      display_name?: string | null;
      email?: string | null;
    };
    const row = (membershipRes.data?.[0] ?? null) as {
      organization_id?: string;
      role?: string;
      organizations?: { name?: string } | { name?: string }[] | null;
    } | null;

    const organization = Array.isArray(row?.organizations)
      ? row?.organizations[0]
      : row?.organizations;

    const role =
      profile.global_role === "superadmin"
        ? "superadmin"
        : row?.role === "admin" || row?.role === "user"
          ? row.role
          : null;

    setMembership({
      role,
      organizationId: row?.organization_id ?? null,
      organizationName: organization?.name ?? null,
      displayName:
        profile.display_name ?? nextSession.user.user_metadata?.name ?? nextSession.user.email ?? null,
    });
  }, []);

  const refreshMembership = useCallback(async () => {
    if (localMockAuthEnabled) {
      loadLocalDemoAuth();
      return;
    }
    if (!supabase) return;
    const { data, error: sessionError } = await supabase.auth.getSession();
    if (sessionError) throw sessionError;
    await loadMembership(data.session);
  }, [loadLocalDemoAuth, loadMembership]);

  useEffect(() => {
    let active = true;

    async function boot() {
      if (localMockAuthEnabled) {
        if (active) {
          loadLocalDemoAuth();
          setLoading(false);
        }
        return;
      }

      if (!isSupabaseConfigured || !supabase) {
        if (active) {
          setError(SUPABASE_ENV_MISSING_MESSAGE);
          setLoading(false);
        }
        return;
      }

      try {
        const { data, error: sessionError } = await supabase.auth.getSession();
        if (sessionError) throw sessionError;
        await loadMembership(data.session);
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : "Failed to load session.");
        }
      } finally {
        if (active) setLoading(false);
      }
    }

    void boot();

    if (!supabase) {
      return () => {
        active = false;
      };
    }

    const { data } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      void loadMembership(nextSession).catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to refresh session.");
      });
    });

    return () => {
      active = false;
      data.subscription.unsubscribe();
    };
  }, [loadLocalDemoAuth, loadMembership]);

  const signIn = useCallback(async (email: string, password: string) => {
    if (localMockAuthEnabled) {
      loadLocalDemoAuth();
      return;
    }
    if (!supabase) {
      throw new Error(SUPABASE_ENV_MISSING_MESSAGE);
    }
    const { error: signInError } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    if (signInError) throw signInError;
  }, [loadLocalDemoAuth]);

  const signOut = useCallback(async () => {
    if (localMockAuthEnabled) {
      setSession(null);
      setUser(null);
      setMembership(emptyMembership);
      return;
    }
    if (!supabase) return;
    const { error: signOutError } = await supabase.auth.signOut();
    if (signOutError) throw signOutError;
    setSession(null);
    setUser(null);
    setMembership(emptyMembership);
  }, []);

  const permissions = useMemo(
    () => permissionsForRole(membership.role),
    [membership.role],
  );

  const value: AuthContextValue = {
    session,
    user,
    role: membership.role,
    organizationId: membership.organizationId,
    organizationName: membership.organizationName,
    displayName: membership.displayName,
    loading,
    error,
    permissions,
    signIn,
    signOut,
    refreshMembership,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used inside AuthProvider.");
  }
  return value;
}

export function usePermissions(): AppPermissions {
  return useAuth().permissions;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, role, loading, error, signOut } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-sm text-muted-foreground">
        Loading workspace...
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  if (!role) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-6">
        <div className="w-full max-w-md rounded-md border border-border bg-card p-6 shadow-sm">
          <p className="text-sm font-semibold text-foreground">No workspace access</p>
          <p className="mt-2 text-sm text-muted-foreground">
            Your account is authenticated, but it is not connected to an active Bidded
            organization yet.
          </p>
          {error && <p className="mt-3 text-xs text-destructive">{error}</p>}
          <button
            type="button"
            className="mt-4 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
            onClick={() => void signOut()}
          >
            Sign out
          </button>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
