"use client";

import { CalendarClock, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { PublishJobRow } from "@/components/publish-job";
import { Button, Card, EmptyState, ErrorState, LoadingBlock, PageHeader, Pagination, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDay } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { PLATFORMS, PUBLISH_STATUSES, type Platform, type PublishJob, type PublishStatus } from "@/lib/types";

const LIMIT = 50;

function dayKey(j: PublishJob): string {
  const iso = j.scheduled_at ?? j.published_at ?? j.created_at;
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function PublishingPage() {
  const { orgId } = useAuth();
  const [status, setStatus] = useState<PublishStatus | "">("");
  const [platform, setPlatform] = useState<Platform | "">("");
  const [offset, setOffset] = useState(0);
  useEffect(() => setOffset(0), [status, platform]);

  const jobs = useQuery(`publishing:${orgId}:${status}:${platform}:${offset}`, () => api.publishing.list({ status, platform, limit: LIMIT, offset }), { interval: 15_000 });
  const accounts = useQuery(`accounts:${orgId}`, () => api.social.accounts());
  const projects = useQuery(`projects-all:${orgId}`, () => api.projects.list({ limit: 200 }));
  const accountName = useMemo(() => new Map((accounts.data ?? []).map((a) => [a.id, a.display_name])), [accounts.data]);
  const projectTitle = useMemo(() => new Map((projects.data?.items ?? []).map((p) => [p.id, p.title])), [projects.data]);

  const groups = useMemo(() => {
    const m = new Map<string, PublishJob[]>();
    for (const j of jobs.data?.items ?? []) {
      const k = dayKey(j);
      m.set(k, [...(m.get(k) ?? []), j]);
    }
    return [...m.entries()];
  }, [jobs.data]);

  const upsert = (j: PublishJob) => jobs.setData((prev) => (prev ? { ...prev, items: prev.items.map((x) => (x.id === j.id ? j : x)) } : prev));
  const todayKey = dayKey({ scheduled_at: new Date().toISOString() } as PublishJob);

  return (
    <>
      <PageHeader
        title="Publishing"
        description="Queue of all posts across platforms, grouped by scheduled day."
        actions={
          <Button size="sm" variant="ghost" icon={<RefreshCw className="h-4 w-4" />} onClick={() => jobs.reload(true)}>
            Refresh
          </Button>
        }
      />
      <Card className="mb-6 p-4">
        <div className="grid gap-3 sm:grid-cols-[220px_220px]">
          <Select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value as PublishStatus | "")} placeholder="All statuses" options={[...PUBLISH_STATUSES]} />
          <Select
            aria-label="Filter by platform"
            value={platform}
            onChange={(e) => setPlatform(e.target.value as Platform | "")}
            placeholder="All platforms"
            options={PLATFORMS.map((p) => ({ value: p, label: p === "youtube" ? "YouTube" : "Instagram" }))}
          />
        </div>
      </Card>

      {jobs.loading && !jobs.data ? (
        <LoadingBlock />
      ) : jobs.error ? (
        <Card>
          <ErrorState error={jobs.error} onRetry={() => jobs.reload()} />
        </Card>
      ) : !groups.length ? (
        <Card>
          <EmptyState icon={<CalendarClock className="h-6 w-6" />} title="No publish jobs" description="Schedule posts from a project's Publish tab." />
        </Card>
      ) : (
        <div className="space-y-6">
          {groups.map(([day, list]) => (
            <section key={day}>
              <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-zinc-300">
                {fmtDay(`${day}T12:00:00`)}
                {day === todayKey && <span className="rounded-full bg-accent-500/15 px-2 py-0.5 text-xs text-accent-300">Today</span>}
                <span className="text-xs font-normal text-zinc-500">
                  {list.length} post{list.length === 1 ? "" : "s"}
                </span>
              </h2>
              <Card className="divide-y divide-zinc-800">
                {list.map((j) => (
                  <PublishJobRow key={j.id} job={j} accountName={accountName.get(j.social_account_id)} projectTitle={projectTitle.get(j.project_id)} onChange={upsert} showProject />
                ))}
              </Card>
            </section>
          ))}
          {jobs.data && jobs.data.total > LIMIT && (
            <Card>
              <Pagination total={jobs.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
            </Card>
          )}
        </div>
      )}
    </>
  );
}
