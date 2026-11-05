"use client";

import { Save, Trash2, UserPlus, Users } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useToast } from "@/components/toast";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ConfirmButton,
  EmptyState,
  ErrorState,
  Input,
  LoadingBlock,
  PageHeader,
  Pagination,
  Select,
  Table,
} from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtRelative, humanize } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { ROLES, type Organization, type Role } from "@/lib/types";

const LOG_LIMIT = 25;
const ROLE_HELP: Record<Role, string> = {
  viewer: "Read-only access",
  reviewer: "Can approve or reject publishing",
  editor: "Create & edit channels, projects, renders, posts",
  admin: "Manage team, API keys and accounts",
  owner: "Full control",
};

function OrgSettings() {
  const { orgId, reloadUser } = useAuth();
  const toast = useToast();
  const org = useQuery(`org:${orgId}`, () => api.orgs.current());
  return (
    <Card>
      <CardHeader title="Organization" description="Name and monthly AI token budget." />
      <CardBody>
        {org.loading && !org.data ? (
          <LoadingBlock />
        ) : org.error ? (
          <ErrorState error={org.error} />
        ) : org.data ? (
          <OrgForm
            key={org.data.updated_at}
            org={org.data}
            onSave={async (name, budget) => {
              try {
                const o = await api.orgs.update({ name, monthly_token_budget: budget });
                org.setData(o);
                toast.success("Organization updated");
                await reloadUser();
              } catch (e) {
                toast.error(e);
                throw e;
              }
            }}
          />
        ) : null}
      </CardBody>
    </Card>
  );
}

function OrgForm({ org, onSave }: { org: Organization; onSave: (name: string, budget: number | null) => Promise<void> }) {
  const [name, setName] = useState(org.name);
  const [budget, setBudget] = useState(org.monthly_token_budget?.toString() ?? "");
  const [busy, setBusy] = useState(false);
  const [fe, setFe] = useState<Record<string, string>>({});
  return (
    <form
      className="grid gap-4 sm:grid-cols-[1fr_220px_auto] sm:items-end"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setFe({});
        try {
          await onSave(name.trim(), budget === "" ? null : Number(budget));
        } catch (err) {
          if (err instanceof ApiError) setFe(err.fieldErrors);
        } finally {
          setBusy(false);
        }
      }}
    >
      <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} minLength={2} maxLength={200} error={fe.name} />
      <Input label="Monthly token budget" type="number" min={0} value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="Unlimited" error={fe.monthly_token_budget} />
      <Button type="submit" variant="primary" loading={busy} icon={<Save className="h-4 w-4" />}>
        Save
      </Button>
      <p className="text-xs text-zinc-500 sm:col-span-3">
        Slug <code className="text-zinc-400">{org.slug}</code> · plan <Badge>{org.plan}</Badge>
      </p>
    </form>
  );
}

function Members() {
  const { orgId, can, user, reloadUser } = useAuth();
  const toast = useToast();
  const members = useQuery(`members:${orgId}`, () => api.orgs.members());
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("editor");
  const [busy, setBusy] = useState(false);
  const [fe, setFe] = useState<Record<string, string>>({});
  const admin = can("admin");
  const ownerCanAssign = can("owner");
  const roleOptions = ROLES.filter((r) => ownerCanAssign || r !== "owner").map((r) => ({ value: r, label: humanize(r) }));

  const add = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setFe({});
    try {
      const m = await api.orgs.addMember(email.trim(), role);
      members.setData((prev) => [...(prev ?? []).filter((x) => x.user_id !== m.user_id), m]);
      toast.success(`${m.email} added as ${m.role}`);
      setEmail("");
    } catch (err) {
      if (err instanceof ApiError) setFe(err.fieldErrors);
      toast.error(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader title="Members" description="People with access to this organization." />
      {admin && (
        <form onSubmit={add} className="grid gap-3 border-b border-zinc-800 p-5 sm:grid-cols-[1fr_180px_auto] sm:items-end">
          <Input label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="teammate@company.com" error={fe.email} hint="The user must already have an account." />
          <Select label="Role" value={role} onChange={(e) => setRole(e.target.value as Role)} options={roleOptions} hint={ROLE_HELP[role]} />
          <Button type="submit" variant="primary" loading={busy} disabled={!email} icon={<UserPlus className="h-4 w-4" />} className="sm:mb-5">
            Add member
          </Button>
        </form>
      )}
      {members.loading && !members.data ? (
        <LoadingBlock />
      ) : members.error ? (
        <ErrorState error={members.error} onRetry={() => members.reload()} />
      ) : !members.data?.length ? (
        <EmptyState icon={<Users className="h-6 w-6" />} title="No members" />
      ) : (
        <Table>
          <thead>
            <tr>
              <th>Member</th>
              <th>Role</th>
              <th>Joined</th>
              {admin && <th className="text-right">Actions</th>}
            </tr>
          </thead>
          <tbody>
            {members.data.map((m) => {
              const self = m.user_id === user?.id;
              return (
                <tr key={m.user_id}>
                  <td>
                    <p className="font-medium text-zinc-100">
                      {m.full_name || m.email}
                      {self && (
                        <Badge tone="accent" className="ml-2">
                          You
                        </Badge>
                      )}
                    </p>
                    <p className="text-xs text-zinc-500">{m.email}</p>
                  </td>
                  <td className="w-48">
                    {admin && !self && (m.role !== "owner" || ownerCanAssign) ? (
                      <Select
                        aria-label={`Role for ${m.email}`}
                        className="h-8"
                        value={m.role}
                        options={roleOptions}
                        onChange={async (e) => {
                          try {
                            const u = await api.orgs.updateMember(m.user_id, e.target.value as Role);
                            members.setData((prev) => (prev ?? []).map((x) => (x.user_id === u.user_id ? u : x)));
                            toast.success("Role updated");
                          } catch (err) {
                            toast.error(err);
                          }
                        }}
                      />
                    ) : (
                      <Badge tone={m.role === "owner" ? "purple" : m.role === "admin" ? "accent" : "zinc"}>{humanize(m.role)}</Badge>
                    )}
                  </td>
                  <td className="whitespace-nowrap text-zinc-500" title={fmtDate(m.joined_at)}>
                    {fmtRelative(m.joined_at)}
                  </td>
                  {admin && (
                    <td className="text-right">
                      {(m.role !== "owner" || ownerCanAssign) && (
                        <ConfirmButton
                          size="xs"
                          icon={<Trash2 className="h-3.5 w-3.5" />}
                          title={self ? "Leave organization" : "Remove member"}
                          confirmLabel={self ? "Leave" : "Remove"}
                          message={self ? "You will lose access to this organization." : `Remove ${m.email} from this organization?`}
                          onConfirm={async () => {
                            try {
                              await api.orgs.removeMember(m.user_id);
                              toast.success(self ? "You left the organization" : "Member removed");
                              if (self) await reloadUser();
                              else members.setData((prev) => (prev ?? []).filter((x) => x.user_id !== m.user_id));
                            } catch (err) {
                              toast.error(err);
                            }
                          }}
                        >
                          {self ? "Leave" : "Remove"}
                        </ConfirmButton>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
    </Card>
  );
}

function AuditLog() {
  const { orgId } = useAuth();
  const [offset, setOffset] = useState(0);
  const logs = useQuery(`audit:${orgId}:${offset}`, () => api.orgs.auditLogs({ limit: LOG_LIMIT, offset }));
  const members = useQuery(`members:${orgId}`, () => api.orgs.members());
  const who = new Map((members.data ?? []).map((m) => [m.user_id, m.full_name || m.email]));
  return (
    <Card>
      <CardHeader title="Audit log" description="Security-relevant actions in this organization." />
      {logs.loading && !logs.data ? (
        <LoadingBlock />
      ) : logs.error ? (
        <ErrorState error={logs.error} onRetry={() => logs.reload()} />
      ) : !logs.data?.items.length ? (
        <EmptyState title="No audit entries yet" />
      ) : (
        <>
          <Table>
            <thead>
              <tr>
                <th>When</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Entity</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {logs.data.items.map((l) => (
                <tr key={l.id}>
                  <td className="whitespace-nowrap text-zinc-400">{fmtDate(l.created_at)}</td>
                  <td className="whitespace-nowrap">{l.actor_id ? (who.get(l.actor_id) ?? l.actor_id.slice(0, 8)) : "System"}</td>
                  <td>
                    <code className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-200">{l.action}</code>
                  </td>
                  <td className="whitespace-nowrap text-xs text-zinc-400">
                    {l.entity_type ?? "—"}
                    {l.entity_id ? ` · ${l.entity_id.slice(0, 8)}` : ""}
                  </td>
                  <td className="max-w-md truncate font-mono text-xs text-zinc-500" title={JSON.stringify(l.data)}>
                    {Object.keys(l.data ?? {}).length ? JSON.stringify(l.data) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
          <Pagination total={logs.data.total} limit={LOG_LIMIT} offset={offset} onChange={setOffset} />
        </>
      )}
    </Card>
  );
}

export default function TeamPage() {
  const { can } = useAuth();
  return (
    <>
      <PageHeader title="Team" description="Members, roles and audit trail." />
      <div className="space-y-6">
        {can("admin") && <OrgSettings />}
        <Members />
        {can("admin") && <AuditLog />}
      </div>
    </>
  );
}
