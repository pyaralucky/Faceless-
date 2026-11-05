"use client";

import { ArrowLeft, Bot, Film, FolderOpen, LayoutList, Send } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback } from "react";
import { AgentsTab } from "@/components/project/agents-tab";
import { AssetsTab } from "@/components/project/assets-tab";
import { OverviewTab } from "@/components/project/overview-tab";
import { PublishTab } from "@/components/project/publish-tab";
import { RenderTab } from "@/components/project/render-tab";
import { Badge, Card, ErrorState, LoadingBlock, StatusBadge, Tabs } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDuration, humanize } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import type { Project } from "@/lib/types";

const TABS = ["overview", "agents", "assets", "render", "publish"] as const;
type Tab = (typeof TABS)[number];

function Workspace() {
  const { id } = useParams<{ id: string }>();
  const { orgId } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const tabParam = params.get("tab") as Tab | null;
  const tab: Tab = tabParam && (TABS as readonly string[]).includes(tabParam) ? tabParam : "overview";

  const project = useQuery(`project:${orgId}:${id}`, () => api.projects.get(id));
  const channelId = project.data?.channel_id;
  const channel = useQuery(channelId ? `channel:${channelId}` : null, () => api.channels.get(channelId as string));
  const setProjectData = project.setData;
  const onChange = useCallback((p: Project) => setProjectData(p), [setProjectData]);

  const setTab = (t: Tab) => {
    const sp = new URLSearchParams(params.toString());
    sp.set("tab", t);
    sp.delete("run");
    sp.delete("render");
    router.replace(`${pathname}?${sp.toString()}`, { scroll: false });
  };

  if (project.loading && !project.data) return <LoadingBlock label="Loading project…" />;
  if (project.error && !project.data)
    return (
      <Card>
        <ErrorState error={project.error} onRetry={() => project.reload()} />
      </Card>
    );
  const p = project.data;
  if (!p) return null;

  return (
    <>
      <div className="mb-6">
        <Link href="/projects" className="mb-3 inline-flex items-center gap-1 text-sm text-zinc-400 hover:text-zinc-200">
          <ArrowLeft className="h-4 w-4" /> Projects
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="min-w-0 text-2xl font-semibold tracking-tight text-zinc-50">{p.title}</h1>
          <StatusBadge status={p.status} />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-zinc-400">
          {channel.data && (
            <Link href={`/projects?channel_id=${channel.data.id}`} className="hover:text-zinc-200">
              {channel.data.name}
            </Link>
          )}
          <Badge>{humanize(p.format)}</Badge>
          <Badge>{fmtDuration(p.target_duration_sec)} target</Badge>
        </div>
      </div>

      <Tabs
        className="mb-6"
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "overview", label: "Overview", icon: <LayoutList className="h-4 w-4" /> },
          { value: "agents", label: "AI Agents", icon: <Bot className="h-4 w-4" /> },
          { value: "assets", label: "Assets", icon: <FolderOpen className="h-4 w-4" /> },
          { value: "render", label: "Render", icon: <Film className="h-4 w-4" /> },
          { value: "publish", label: "Publish", icon: <Send className="h-4 w-4" /> },
        ]}
      />

      {tab === "overview" && <OverviewTab key={p.updated_at} project={p} channel={channel.data} onChange={onChange} />}
      {tab === "agents" && <AgentsTab project={p} onChange={onChange} initialRunId={params.get("run")} />}
      {tab === "assets" && <AssetsTab projectId={p.id} />}
      {tab === "render" && <RenderTab project={p} channel={channel.data} initialRenderId={params.get("render")} />}
      {tab === "publish" && <PublishTab project={p} channel={channel.data} />}
    </>
  );
}

export default function ProjectPage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <Workspace />
    </Suspense>
  );
}
