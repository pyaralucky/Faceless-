"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, getStoredOrgId, setStoredOrgId } from "./api";
import { roleAtLeast } from "./format";
import type { LoginRequest, Me, Membership, Organization, RegisterRequest, Role } from "./types";

export type AuthStatus = "loading" | "authenticated" | "anonymous";

export interface AuthContextValue {
  status: AuthStatus;
  user: Me | null;
  memberships: Membership[];
  orgId: string | null;
  membership: Membership | null;
  role: Role | null;
  /** True when the user's role in the current org is >= `min` (superusers always pass). */
  can: (min: Role) => boolean;
  selectOrg: (id: string) => void;
  createOrg: (name: string) => Promise<Organization>;
  login: (data: LoginRequest) => Promise<void>;
  register: (data: RegisterRequest) => Promise<void>;
  logout: () => Promise<void>;
  reloadUser: () => Promise<Me | null>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function pickOrg(me: Me, preferred: string | null): string | null {
  if (preferred && me.memberships.some((m) => m.organization_id === preferred)) return preferred;
  return me.memberships[0]?.organization_id ?? null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<Me | null>(null);
  const [orgId, setOrgId] = useState<string | null>(null);

  const applyUser = useCallback((me: Me | null, preferredOrg?: string | null) => {
    setUser(me);
    if (me) {
      const id = pickOrg(me, preferredOrg ?? getStoredOrgId());
      setStoredOrgId(id);
      setOrgId(id);
      setStatus("authenticated");
    } else {
      setOrgId(null);
      setStatus("anonymous");
    }
  }, []);

  const reloadUser = useCallback(async (): Promise<Me | null> => {
    if (!api.client.storage.getAccessToken() && !api.client.storage.getRefreshToken()) {
      applyUser(null);
      return null;
    }
    try {
      const me = await api.auth.me();
      applyUser(me);
      return me;
    } catch {
      applyUser(null);
      return null;
    }
  }, [applyUser]);

  useEffect(() => {
    void reloadUser();
  }, [reloadUser]);

  const login = useCallback(
    async (data: LoginRequest) => {
      await api.auth.login(data);
      const me = await api.auth.me();
      applyUser(me);
    },
    [applyUser],
  );

  const register = useCallback(
    async (data: RegisterRequest) => {
      await api.auth.register(data);
      const me = await api.auth.me();
      applyUser(me, me.memberships[0]?.organization_id ?? null);
    },
    [applyUser],
  );

  const logout = useCallback(async () => {
    try {
      await api.auth.logout();
    } catch {
      /* tokens are cleared regardless */
    }
    setStoredOrgId(null);
    applyUser(null);
  }, [applyUser]);

  const selectOrg = useCallback((id: string) => {
    setStoredOrgId(id);
    setOrgId(id);
  }, []);

  const createOrg = useCallback(
    async (name: string) => {
      const org = await api.orgs.create(name);
      const me = await api.auth.me();
      applyUser(me, org.id);
      return org;
    },
    [applyUser],
  );

  const value = useMemo<AuthContextValue>(() => {
    const memberships = user?.memberships ?? [];
    const membership = memberships.find((m) => m.organization_id === orgId) ?? null;
    const role: Role | null = membership?.role ?? (user?.is_superuser && orgId ? "owner" : null);
    return {
      status,
      user,
      memberships,
      orgId,
      membership,
      role,
      can: (min: Role) => Boolean(user?.is_superuser) || roleAtLeast(role, min),
      selectOrg,
      createOrg,
      login,
      register,
      logout,
      reloadUser,
    };
  }, [status, user, orgId, selectOrg, createOrg, login, register, logout, reloadUser]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
