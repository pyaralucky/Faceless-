"use client";

import {
  BarChart3,
  Building2,
  CalendarClock,
  Check,
  ChevronsUpDown,
  ClipboardCheck,
  Clapperboard,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Menu,
  Plus,
  Shield,
  Tv,
  User as UserIcon,
  Users,
  Video,
  Link2,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useToast } from "@/components/toast";
import { Badge, Button, EmptyState, Input, LoadingBlock, Modal } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cx, humanize } from "@/lib/format";
import type { Role } from "@/lib/types";

interface NavItem {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
  minRole?: Role;
  superuser?: boolean;
}

const NAV: { section: string; items: NavItem[] }[] = [
  { section: "Overview", items: [{ href: "/dashboard", label: "Dashboard", icon: LayoutDashboard }] },
  {
    section: "Create",
    items: [
      { href: "/channels", label: "Channels", icon: Tv },
      { href: "/projects", label: "Projects", icon: Clapperboard },
      { href: "/approvals", label: "Approvals", icon: ClipboardCheck },
    ],
  },
  {
    section: "Distribute",
    items: [
      { href: "/accounts", label: "Social accounts", icon: Link2 },
      { href: "/publishing", label: "Publishing", icon: CalendarClock },
      { href: "/analytics", label: "Analytics", icon: BarChart3 },
    ],
  },
  {
    section: "Settings",
    items: [
      { href: "/settings/api", label: "API & models", icon: KeyRound, minRole: "admin" },
      { href: "/settings/team", label: "Team", icon: Users },
      { href: "/settings/profile", label: "Profile", icon: UserIcon },
    ],
  },
  { section: "Platform", items: [{ href: "/admin/users", label: "Users", icon: Shield, superuser: true }] },
];

function CreateOrgModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { createOrg } = useAuth();
  const toast = useToast();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const org = await createOrg(name.trim());
      toast.success(`Organization “${org.name}” created`);
      setName("");
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? (err.fieldErrors.name ?? err.message) : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Create organization"
      description="Organizations are isolated workspaces with their own channels, team and API keys."
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form="create-org-form" loading={busy} disabled={name.trim().length < 2}>
            Create
          </Button>
        </>
      }
    >
      <form id="create-org-form" onSubmit={submit}>
        <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Acme Media" required minLength={2} maxLength={200} error={error} />
      </form>
    </Modal>
  );
}

function OrgSwitcher({ onCreate }: { onCreate: () => void }) {
  const { memberships, orgId, selectOrg, membership } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex w-full items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-left text-sm hover:border-zinc-700"
      >
        <Building2 className="h-4 w-4 shrink-0 text-zinc-500" />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium text-zinc-100">{membership?.organization_name ?? "Select organization"}</span>
          {membership && <span className="block text-xs text-zinc-500">{humanize(membership.role)}</span>}
        </span>
        <ChevronsUpDown className="h-4 w-4 shrink-0 text-zinc-500" />
      </button>
      {open && (
        <div className="absolute left-0 right-0 z-40 mt-1 overflow-hidden rounded-lg border border-zinc-800 bg-zinc-900 shadow-xl" role="listbox">
          <div className="max-h-64 overflow-y-auto py-1">
            {memberships.map((m) => (
              <button
                key={m.organization_id}
                role="option"
                aria-selected={m.organization_id === orgId}
                onClick={() => {
                  selectOrg(m.organization_id);
                  setOpen(false);
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-zinc-800"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-zinc-100">{m.organization_name}</span>
                  <span className="block text-xs text-zinc-500">{humanize(m.role)}</span>
                </span>
                {m.organization_id === orgId && <Check className="h-4 w-4 text-accent-400" />}
              </button>
            ))}
          </div>
          <button
            onClick={() => {
              setOpen(false);
              onCreate();
            }}
            className="flex w-full items-center gap-2 border-t border-zinc-800 px-3 py-2 text-left text-sm text-accent-300 hover:bg-zinc-800"
          >
            <Plus className="h-4 w-4" /> New organization
          </button>
        </div>
      )}
    </div>
  );
}

function Sidebar({ onNavigate, onCreateOrg }: { onNavigate: () => void; onCreateOrg: () => void }) {
  const pathname = usePathname();
  const { can, user } = useAuth();
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-16 items-center gap-2 px-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-600 shadow-lg shadow-accent-900/50">
          <Video className="h-4 w-4 text-white" />
        </div>
        <div className="leading-tight">
          <p className="text-sm font-semibold text-zinc-50">Faceless AI</p>
          <p className="text-[11px] uppercase tracking-wider text-zinc-500">Studio</p>
        </div>
      </div>
      <div className="px-3 pb-3">
        <OrgSwitcher onCreate={onCreateOrg} />
      </div>
      <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-2" aria-label="Main navigation">
        {NAV.map((group) => {
          const items = group.items.filter((i) => (i.superuser ? user?.is_superuser : i.minRole ? can(i.minRole) : true));
          if (!items.length) return null;
          return (
            <div key={group.section}>
              <p className="px-2 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-600">{group.section}</p>
              <ul className="space-y-0.5">
                {items.map((item) => {
                  const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
                  const Icon = item.icon;
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        onClick={onNavigate}
                        aria-current={active ? "page" : undefined}
                        className={cx(
                          "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors",
                          active ? "bg-accent-500/10 font-medium text-accent-200" : "text-zinc-400 hover:bg-zinc-800/70 hover:text-zinc-100",
                        )}
                      >
                        <Icon className={cx("h-4 w-4", active ? "text-accent-400" : "text-zinc-500")} />
                        {item.label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </nav>
      <UserFooter />
    </div>
  );
}

function UserFooter() {
  const { user, logout } = useAuth();
  const router = useRouter();
  if (!user) return null;
  const initials = (user.full_name || user.email)
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase())
    .join("");
  return (
    <div className="flex items-center gap-3 border-t border-zinc-800 p-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-zinc-800 text-xs font-semibold text-zinc-300">{initials}</div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-zinc-200">{user.full_name || user.email}</p>
        <p className="truncate text-xs text-zinc-500">
          {user.email}
          {user.is_superuser && (
            <Badge tone="purple" className="ml-1.5 align-middle">
              superuser
            </Badge>
          )}
        </p>
      </div>
      <button
        onClick={async () => {
          await logout();
          router.replace("/login");
        }}
        className="rounded p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200"
        aria-label="Sign out"
        title="Sign out"
      >
        <LogOut className="h-4 w-4" />
      </button>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { status, orgId, memberships } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => {
    if (status === "anonymous") router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [status, router, pathname]);

  useEffect(() => setMobileOpen(false), [pathname]);

  if (status !== "authenticated") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <LoadingBlock label={status === "loading" ? "Loading your workspace…" : "Redirecting to sign in…"} />
      </div>
    );
  }

  const isOrgFree = pathname.startsWith("/settings/profile") || pathname.startsWith("/admin");

  return (
    <div className="min-h-screen">
      {/* desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-zinc-800 bg-zinc-950 lg:block">
        <Sidebar onNavigate={() => undefined} onCreateOrg={() => setCreateOpen(true)} />
      </aside>

      {/* mobile sidebar */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/70" onClick={() => setMobileOpen(false)} aria-hidden />
          <aside className="absolute inset-y-0 left-0 w-72 max-w-[85vw] border-r border-zinc-800 bg-zinc-950 shadow-2xl">
            <button className="absolute right-3 top-4 rounded p-1 text-zinc-400 hover:bg-zinc-800" onClick={() => setMobileOpen(false)} aria-label="Close navigation">
              <X className="h-5 w-5" />
            </button>
            <Sidebar onNavigate={() => setMobileOpen(false)} onCreateOrg={() => setCreateOpen(true)} />
          </aside>
        </div>
      )}

      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-zinc-800 bg-zinc-950/80 px-4 backdrop-blur lg:hidden">
          <button onClick={() => setMobileOpen(true)} className="rounded p-1.5 text-zinc-300 hover:bg-zinc-800" aria-label="Open navigation">
            <Menu className="h-5 w-5" />
          </button>
          <span className="text-sm font-semibold">Faceless AI Studio</span>
        </header>
        <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {!orgId && memberships.length === 0 && !isOrgFree ? (
            <EmptyState
              icon={<Building2 className="h-6 w-6" />}
              title="You're not a member of any organization yet"
              description="Create an organization to start producing videos, or ask an admin to invite you."
              action={
                <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setCreateOpen(true)}>
                  Create organization
                </Button>
              }
            />
          ) : (
            <div key={orgId ?? "none"}>{children}</div>
          )}
        </main>
      </div>
      <CreateOrgModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}
