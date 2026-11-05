"use client";

import { Activity, CalendarClock, CheckCircle2, ClipboardCheck, Clapperboard, Eye, Film, Link2, Tv, XCircle } from "lucide-react";
import Link from "next/link";
import { Badge, Card, CardBody, CardHeader, EmptyState, ErrorState, LoadingBlock, PageHeader, ProgressBar, Stat, StatusBadge } from "@/components/ui";
import { PlatformIcon } from "@/components/platform";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtCompact, fmtDate, fmtNumber, fmtRelative, fmtUsd, humanize } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { PROJECT_STATUSES } from "@/lib/types";

export default function DashboardPage() {
  const { orgId, membership } = useAuth();
  const { data, error, loading, reload } = useQuery(`dashboard:${orgId}`, () => api.dashboard.get(), { interval: 10_000 });

  return (
    <>
      <PageHeader
        title="Dashboard"
        description={membership ? `Overview of ${membership.organization_name}. Refreshes every 10 seconds.` : undefined}
      />
      {loading && !data ? (
        <LoadingBlock />
      ) : error && !data ? (
        <Card>
          <ErrorState error={error} onRetry={() => reload()} />
        </Card>
      ) : data ? (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Stat label="Channels" value={fmtNumber(data.counts.channels)} icon={<Tv className="h-4 w-4" />} />
            <Stat label="Projects" value={fmtNumber(data.counts.projects)} icon={<Clapperboard className="h-4 w-4" />} />
            <Stat label="Total views" value={fmtCompact(data.total_views)} icon={<Eye className="h-4 w-4" />} />
            <Stat label="Renders (30d)" value={fmtNumber(data.counts.renders_30d)} icon={<Film className="h-4 w-4" />} />
            <Stat
              label="Pending approvals"
              value={fmtNumber(data.counts.pending_approvals)}
              icon={<ClipboardCheck className="h-4 w-4" />}
              tone={data.counts.pending_approvals ? "amber" : undefined}
            />
            <Stat label="Scheduled posts" value={fmtNumber(data.counts.scheduled_posts)} icon={<CalendarClock className="h-4 w-4" />} />
            <Stat label="Published posts" value={fmtNumber(data.counts.published_posts)} icon={<CheckCircle2 className="h-4 w-4" />} tone="green" />
            <Stat
              label="Failed posts"
              value={fmtNumber(data.counts.failed_posts)}
              icon={<XCircle className="h-4 w-4" />}
              tone={data.counts.failed_posts ? "red" : undefined}
            />
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader title="Project pipeline" description="Projects by status" />
              <CardBody>
                <StatusBreakdown counts={data.project_status} />
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="Token usage" description="AI agent consumption" />
              <CardBody className="space-y-5">
                <Usage usage={data.usage} />
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <p className="text-xs uppercase tracking-wide text-zinc-500">Tokens (30d)</p>
                    <p className="mt-1 font-semibold tabular-nums text-zinc-100">{fmtNumber(data.usage.tokens_30d)}</p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-wide text-zinc-500">Cost (30d)</p>
                    <p className="mt-1 font-semibold tabular-nums text-zinc-100">{fmtUsd(data.usage.cost_usd_30d, 2)}</p>
                  </div>
                  <div className="col-span-2 flex items-center gap-2 text-xs text-zinc-500">
                    <Link2 className="h-3.5 w-3.5" /> {fmtNumber(data.counts.social_accounts)} connected social accounts
                  </div>
                </div>
              </CardBody>
            </Card>
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <Card>
              <CardHeader title="Upcoming posts" actions={<Link href="/publishing" className="text-xs text-accent-300 hover:text-accent-200">View queue</Link>} />
              {data.upcoming_posts.length === 0 ? (
                <EmptyState title="Nothing scheduled" description="Scheduled and pending posts will appear here." />
              ) : (
                <ul className="divide-y divide-zinc-800">
                  {data.upcoming_posts.map((p) => (
                    <li key={p.id} className="flex items-center gap-3 px-5 py-3">
                      <PlatformIcon platform={p.platform} />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm text-zinc-200">{p.title || "Untitled"}</p>
                        <p className="text-xs text-zinc-500">{p.scheduled_at ? `${fmtDate(p.scheduled_at)} · ${fmtRelative(p.scheduled_at)}` : "As soon as approved"}</p>
                      </div>
                      <StatusBadge status={p.status} />
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card>
              <CardHeader title="Recent agent runs" />
              {data.recent_agent_runs.length === 0 ? (
                <EmptyState title="No agent runs yet" description="Start a run from a project's AI Agents tab." />
              ) : (
                <ul className="divide-y divide-zinc-800">
                  {data.recent_agent_runs.map((r) => (
                    <li key={r.id}>
                      <Link href={`/projects/${r.project_id}?tab=agents&run=${r.id}`} className="flex items-center gap-3 px-5 py-3 hover:bg-zinc-800/30">
                        <Activity className="h-4 w-4 text-zinc-500" />
                        <div className="min-w-0 flex-1">
                          <p className="text-sm text-zinc-200">{fmtNumber(r.tokens)} tokens</p>
                          <p className="text-xs text-zinc-500">{fmtRelative(r.created_at)}</p>
                        </div>
                        <StatusBadge status={r.status} />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card>
              <CardHeader title="Active renders" />
              {data.active_renders.length === 0 ? (
                <EmptyState title="No renders in progress" icon={<Film className="h-6 w-6" />} />
              ) : (
                <ul className="divide-y divide-zinc-800">
                  {data.active_renders.map((r) => (
                    <li key={r.id}>
                      <Link href={`/projects/${r.project_id}?tab=render&render=${r.id}`} className="block space-y-2 px-5 py-3 hover:bg-zinc-800/30">
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-zinc-300">{humanize(r.stage) || "Queued"}</span>
                          <span className="tabular-nums text-zinc-400">{Math.round(r.progress)}%</span>
                        </div>
                        <ProgressBar value={r.progress} label={`Render ${r.stage}`} />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      ) : null}
    </>
  );
}

function StatusBreakdown({ counts }: { counts: Record<string, number | undefined> }) {
  const entries = PROJECT_STATUSES.map((s) => [s, counts[s] ?? 0] as const).filter(([, n]) => n > 0);
  const total = entries.reduce((a, [, n]) => a + n, 0);
  if (!total) return <EmptyState title="No projects yet" description="Create a project to start your pipeline." />;
  const max = Math.max(...entries.map(([, n]) => n));
  return (
    <ul className="space-y-3">
      {entries.map(([status, n]) => (
        <li key={status} className="grid grid-cols-[140px_1fr_48px] items-center gap-3 text-sm">
          <StatusBadge status={status} />
          <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
            <div className="h-full rounded-full bg-accent-500/80" style={{ width: `${(n / max) * 100}%` }} />
          </div>
          <span className="text-right tabular-nums text-zinc-300">{n}</span>
        </li>
      ))}
    </ul>
  );
}

function Usage({ usage }: { usage: { tokens_this_month: number; monthly_token_budget: number | null } }) {
  const budget = usage.monthly_token_budget;
  const pct = budget ? (usage.tokens_this_month / budget) * 100 : 0;
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-2xl font-semibold tabular-nums text-zinc-50">{fmtCompact(usage.tokens_this_month)}</span>
        <span className="text-sm text-zinc-500">{budget ? `of ${fmtCompact(budget)} this month` : "this month"}</span>
      </div>
      {budget ? (
        <>
          <ProgressBar value={pct} tone={pct >= 90 ? "red" : pct >= 70 ? "amber" : "accent"} label="Monthly token budget used" />
          <p className="mt-2 text-xs text-zinc-500">{pct.toFixed(1)}% of monthly budget used</p>
        </>
      ) : (
        <Badge tone="zinc">No monthly budget set</Badge>
      )}
    </div>
  );
}
