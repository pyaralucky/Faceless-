"use client";

import { Search, Shield } from "lucide-react";
import { useEffect, useState } from "react";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, ErrorState, Input, LoadingBlock, NoAccess, PageHeader, Pagination, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtRelative } from "@/lib/format";
import { useDebounced, useQuery } from "@/lib/hooks";
import type { User } from "@/lib/types";

const LIMIT = 50;

export default function AdminUsersPage() {
  const { user } = useAuth();
  const toast = useToast();
  const [q, setQ] = useState("");
  const dq = useDebounced(q, 350);
  const [offset, setOffset] = useState(0);
  useEffect(() => setOffset(0), [dq]);
  const users = useQuery(user?.is_superuser ? `admin-users:${dq}:${offset}` : null, () => api.users.list({ q: dq || undefined, limit: LIMIT, offset }));
  const [busy, setBusy] = useState<string | null>(null);

  if (!user?.is_superuser) return <NoAccess need="platform superuser" />;

  const update = async (u: User, patch: { is_active?: boolean; is_superuser?: boolean }, msg: string) => {
    setBusy(u.id);
    try {
      const updated = await api.users.update(u.id, patch);
      users.setData((prev) => (prev ? { ...prev, items: prev.items.map((x) => (x.id === updated.id ? updated : x)) } : prev));
      toast.success(msg);
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <PageHeader title="Users" description="Platform-wide user administration (superusers only)." />
      <Card>
        <div className="border-b border-zinc-800 p-4">
          <div className="relative max-w-md">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
            <Input aria-label="Search users" placeholder="Search by email or name…" value={q} onChange={(e) => setQ(e.target.value)} className="pl-9" />
          </div>
        </div>
        {users.loading && !users.data ? (
          <LoadingBlock />
        ) : users.error ? (
          <ErrorState error={users.error} onRetry={() => users.reload()} />
        ) : !users.data?.items.length ? (
          <EmptyState title="No users found" />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <th>User</th>
                  <th>Status</th>
                  <th>Last sign-in</th>
                  <th>Created</th>
                  <th className="text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.data.items.map((u) => {
                  const self = u.id === user.id;
                  return (
                    <tr key={u.id}>
                      <td>
                        <p className="font-medium text-zinc-100">{u.full_name || "—"}</p>
                        <p className="text-xs text-zinc-500">{u.email}</p>
                      </td>
                      <td>
                        <div className="flex flex-wrap gap-1">
                          <Badge tone={u.is_active ? "green" : "red"}>{u.is_active ? "Active" : "Deactivated"}</Badge>
                          {u.is_superuser && (
                            <Badge tone="purple">
                              <Shield className="h-3 w-3" /> Superuser
                            </Badge>
                          )}
                          {!u.email_verified && <Badge tone="amber">Unverified</Badge>}
                        </div>
                      </td>
                      <td className="whitespace-nowrap text-zinc-400">{u.last_login_at ? fmtRelative(u.last_login_at) : "Never"}</td>
                      <td className="whitespace-nowrap text-zinc-500">{fmtDate(u.created_at)}</td>
                      <td>
                        <div className="flex justify-end gap-2">
                          <Button
                            size="xs"
                            variant={u.is_active ? "ghost" : "success"}
                            disabled={self || busy === u.id}
                            title={self ? "You cannot deactivate yourself" : undefined}
                            onClick={() => update(u, { is_active: !u.is_active }, u.is_active ? "User deactivated" : "User activated")}
                          >
                            {u.is_active ? "Deactivate" : "Activate"}
                          </Button>
                          <Button
                            size="xs"
                            variant="ghost"
                            disabled={self || busy === u.id}
                            title={self ? "You cannot demote yourself" : undefined}
                            onClick={() => update(u, { is_superuser: !u.is_superuser }, u.is_superuser ? "Superuser revoked" : "Superuser granted")}
                          >
                            {u.is_superuser ? "Revoke superuser" : "Make superuser"}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
            <Pagination total={users.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </>
        )}
      </Card>
    </>
  );
}
