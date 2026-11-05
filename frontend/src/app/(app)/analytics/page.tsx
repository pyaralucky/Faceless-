"use client";

import { BarChart3, ExternalLink, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { LineChart } from "@/components/line-chart";
import { PlatformIcon, platformLabel } from "@/components/platform";
import { useToast } from "@/components/toast";
import { Button, Card, CardBody, CardHeader, EmptyState, ErrorState, LoadingBlock, PageHeader, Select, Stat, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtCompact, fmtDate, fmtNumber, fmtPct } from "@/lib/format";
import { useQuery } from "@/lib/hooks";

const RANGES = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "365", label: "Last 12 months" },
];

export default function AnalyticsPage() {
  const { orgId, can } = useAuth();
  const toast = useToast();
  const [days, setDays] = useState("30");
  const [channelId, setChannelId] = useState("");
  const [collecting, setCollecting] = useState(false);
  const channels = useQuery(`channels:${orgId}`, () => api.channels.list(true));
  const report = useQuery(`analytics:${orgId}:${days}:${channelId}`, () => api.analytics.report({ days: Number(days), channel_id: channelId || undefined }));

  const collect = async () => {
    setCollecting(true);
    try {
      const r = await api.analytics.collect();
      toast.success(r.message || "Collection started — refresh in a minute");
    } catch (e) {
      toast.error(e);
    } finally {
      setCollecting(false);
    }
  };

  const t = report.data?.totals ?? {};
  const platforms = Object.entries(report.data?.by_platform ?? {});

  return (
    <>
      <PageHeader
        title="Analytics"
        description={report.data ? `${fmtDate(report.data.period_start)} – ${fmtDate(report.data.period_end)}` : "Performance of published videos."}
        actions={
          <>
            <Button size="sm" variant="ghost" icon={<RefreshCw className="h-4 w-4" />} onClick={() => report.reload()}>
              Refresh
            </Button>
            {can("editor") && (
              <Button size="sm" variant="primary" loading={collecting} onClick={collect}>
                Collect now
              </Button>
            )}
          </>
        }
      />
      <Card className="mb-6 p-4">
        <div className="grid gap-3 sm:grid-cols-[200px_240px]">
          <Select aria-label="Time range" value={days} onChange={(e) => setDays(e.target.value)} options={RANGES} />
          <Select aria-label="Channel" value={channelId} onChange={(e) => setChannelId(e.target.value)} placeholder="All channels" options={(channels.data ?? []).map((c) => ({ value: c.id, label: c.name }))} />
        </div>
      </Card>

      {report.loading && !report.data ? (
        <LoadingBlock />
      ) : report.error ? (
        <Card>
          <ErrorState error={report.error} onRetry={() => report.reload()} />
        </Card>
      ) : report.data ? (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4 xl:grid-cols-7">
            <Stat label="Views" value={fmtCompact(t.views ?? 0)} />
            <Stat label="Likes" value={fmtCompact(t.likes ?? 0)} />
            <Stat label="Comments" value={fmtCompact(t.comments ?? 0)} />
            <Stat label="Shares" value={fmtCompact(t.shares ?? 0)} />
            <Stat label="Watch time" value={`${fmtCompact((t.watch_time_minutes ?? 0) / 60)} h`} />
            <Stat label="Posts" value={fmtNumber(t.posts ?? 0)} />
            <Stat label="Engagement" value={fmtPct(t.engagement_rate ?? 0)} hint="(likes+comments+shares) / views" />
          </div>

          <Card>
            <CardHeader title="Cumulative views" description="Latest snapshot per post, summed per day" />
            <CardBody>
              <LineChart points={report.data.daily.map((d) => ({ x: d.date, y: d.cumulative_views }))} label="Views" />
            </CardBody>
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader title="By platform" />
              {platforms.length === 0 ? (
                <EmptyState title="No published posts in this period" />
              ) : (
                <Table>
                  <thead>
                    <tr>
                      <th>Platform</th>
                      <th className="text-right">Posts</th>
                      <th className="text-right">Views</th>
                      <th className="text-right">Likes</th>
                      <th className="text-right">Engagement</th>
                    </tr>
                  </thead>
                  <tbody>
                    {platforms.map(([p, m]) => (
                      <tr key={p}>
                        <td>
                          <span className="flex items-center gap-2">
                            <PlatformIcon platform={p} /> {platformLabel(p)}
                          </span>
                        </td>
                        <td className="text-right tabular-nums">{fmtNumber(m.posts)}</td>
                        <td className="text-right tabular-nums">{fmtNumber(m.views)}</td>
                        <td className="text-right tabular-nums">{fmtNumber(m.likes)}</td>
                        <td className="text-right tabular-nums">{fmtPct(m.engagement_rate)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card>
            <Card>
              <CardHeader title="By channel" />
              {report.data.by_channel.length === 0 ? (
                <EmptyState title="No channel data" />
              ) : (
                <Table>
                  <thead>
                    <tr>
                      <th>Channel</th>
                      <th className="text-right">Posts</th>
                      <th className="text-right">Views</th>
                      <th className="text-right">Likes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.data.by_channel.map((c) => (
                      <tr key={c.channel_id}>
                        <td className="text-zinc-200">{c.name}</td>
                        <td className="text-right tabular-nums">{fmtNumber(c.posts)}</td>
                        <td className="text-right tabular-nums">{fmtNumber(c.views)}</td>
                        <td className="text-right tabular-nums">{fmtNumber(c.likes)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card>
          </div>

          <Card>
            <CardHeader title="Top posts" description="Ranked by views" />
            {report.data.top_posts.length === 0 ? (
              <EmptyState icon={<BarChart3 className="h-6 w-6" />} title="No posts yet" description="Published videos and their metrics will appear here after the next collection." />
            ) : (
              <Table>
                <thead>
                  <tr>
                    <th>Post</th>
                    <th>Published</th>
                    <th className="text-right">Views</th>
                    <th className="text-right">Likes</th>
                    <th className="text-right">Comments</th>
                    <th className="text-right">Shares</th>
                    <th className="text-right">Watch (min)</th>
                    <th className="text-right">Engagement</th>
                  </tr>
                </thead>
                <tbody>
                  {report.data.top_posts.map((r) => (
                    <tr key={r.publish_job_id}>
                      <td className="max-w-xs">
                        <div className="flex items-center gap-2">
                          <PlatformIcon platform={r.platform} />
                          <Link href={`/projects/${r.project_id}?tab=publish`} className="truncate text-zinc-100 hover:text-accent-300">
                            {r.title || "Untitled"}
                          </Link>
                          {r.external_url && (
                            <a href={r.external_url} target="_blank" rel="noopener noreferrer" className="text-zinc-500 hover:text-zinc-200" aria-label="Open post">
                              <ExternalLink className="h-3.5 w-3.5" />
                            </a>
                          )}
                        </div>
                      </td>
                      <td className="whitespace-nowrap text-zinc-500">{fmtDate(r.published_at)}</td>
                      <td className="text-right tabular-nums">{fmtNumber(r.views)}</td>
                      <td className="text-right tabular-nums">{fmtNumber(r.likes)}</td>
                      <td className="text-right tabular-nums">{fmtNumber(r.comments)}</td>
                      <td className="text-right tabular-nums">{fmtNumber(r.shares)}</td>
                      <td className="text-right tabular-nums">{fmtNumber(r.watch_time_minutes)}</td>
                      <td className="text-right tabular-nums">{fmtPct(r.engagement_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </div>
      ) : null}
    </>
  );
}
