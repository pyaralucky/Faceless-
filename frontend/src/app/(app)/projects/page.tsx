"use client";

import { Clapperboard, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState, type FormEvent } from "react";
import { useToast } from "@/components/toast";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  FormError,
  Input,
  LoadingBlock,
  Modal,
  PageHeader,
  Pagination,
  Select,
  StatusBadge,
  Table,
  Textarea,
} from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDuration, fmtRelative, humanize } from "@/lib/format";
import { useDebounced, useQuery } from "@/lib/hooks";
import { PROJECT_STATUSES, VIDEO_FORMATS, type Channel, type ProjectStatus, type VideoFormat } from "@/lib/types";

const LIMIT = 25;

function NewProjectModal({ channels, defaultChannel, onClose }: { channels: Channel[]; defaultChannel?: string; onClose: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const [channelId, setChannelId] = useState(defaultChannel || channels[0]?.id || "");
  const channel = channels.find((c) => c.id === channelId);
  const [title, setTitle] = useState("");
  const [topic, setTopic] = useState("");
  const [format, setFormat] = useState<VideoFormat | "">("");
  const [duration, setDuration] = useState(60);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [fe, setFe] = useState<Record<string, string>>({});

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setFe({});
    try {
      const p = await api.projects.create({
        channel_id: channelId,
        title: title.trim(),
        topic: topic.trim(),
        format: format || null,
        target_duration_sec: duration,
      });
      toast.success("Project created");
      router.push(`/projects/${p.id}`);
    } catch (err) {
      setError(err);
      if (err instanceof ApiError) setFe(err.fieldErrors);
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="New project"
      description="A project is a single video: brief → AI agents → assets → render → publish."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form="new-project" loading={busy} disabled={!channelId || !title.trim()}>
            Create project
          </Button>
        </>
      }
    >
      {channels.length === 0 ? (
        <EmptyState
          title="Create a channel first"
          description="Projects belong to a channel."
          action={
            <Link href="/channels">
              <Button variant="primary">Go to channels</Button>
            </Link>
          }
        />
      ) : (
        <form id="new-project" onSubmit={submit} className="space-y-4">
          <Select
            label="Channel"
            required
            value={channelId}
            onChange={(e) => setChannelId(e.target.value)}
            options={channels.map((c) => ({ value: c.id, label: c.name }))}
            error={fe.channel_id}
          />
          <Input label="Title" required maxLength={300} value={title} onChange={(e) => setTitle(e.target.value)} error={fe.title} placeholder="Why the Moon is drifting away" />
          <Textarea label="Topic" value={topic} onChange={(e) => setTopic(e.target.value)} error={fe.topic} rows={3} placeholder="What the video is about, angle, key points…" />
          <div className="grid gap-4 sm:grid-cols-2">
            <Select
              label="Format"
              value={format}
              onChange={(e) => setFormat(e.target.value as VideoFormat | "")}
              options={[
                { value: "", label: `Channel default (${humanize(channel?.default_format ?? "vertical")})` },
                ...VIDEO_FORMATS.map((f) => ({ value: f, label: humanize(f) })),
              ]}
            />
            <Input
              label="Target duration (sec)"
              type="number"
              min={10}
              max={3600}
              value={duration}
              onChange={(e) => setDuration(Number(e.target.value))}
              error={fe.target_duration_sec}
            />
          </div>
          <FormError error={error} />
        </form>
      )}
    </Modal>
  );
}

function ProjectsInner() {
  const { orgId, can } = useAuth();
  const params = useSearchParams();
  const [channelId, setChannelId] = useState(params.get("channel_id") ?? "");
  const [status, setStatus] = useState<ProjectStatus | "">((params.get("status") as ProjectStatus) ?? "");
  const [q, setQ] = useState("");
  const dq = useDebounced(q, 350);
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(params.get("new") === "1");

  useEffect(() => setOffset(0), [channelId, status, dq]);

  const channels = useQuery(`channels:${orgId}`, () => api.channels.list(true));
  const channelMap = useMemo(() => new Map((channels.data ?? []).map((c) => [c.id, c])), [channels.data]);
  const list = useQuery(`projects:${orgId}:${channelId}:${status}:${dq}:${offset}`, () =>
    api.projects.list({ channel_id: channelId || undefined, status, q: dq || undefined, limit: LIMIT, offset }),
  );

  return (
    <>
      <PageHeader
        title="Projects"
        description="Every video in your pipeline."
        actions={
          can("editor") && (
            <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
              New project
            </Button>
          )
        }
      />
      <Card>
        <div className="grid gap-3 border-b border-zinc-800 p-4 sm:grid-cols-[1fr_200px_200px]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
            <Input aria-label="Search projects" placeholder="Search title or topic…" value={q} onChange={(e) => setQ(e.target.value)} className="pl-9" />
          </div>
          <Select
            aria-label="Filter by channel"
            value={channelId}
            onChange={(e) => setChannelId(e.target.value)}
            placeholder="All channels"
            options={(channels.data ?? []).map((c) => ({ value: c.id, label: c.name }))}
          />
          <Select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value as ProjectStatus | "")} placeholder="All statuses" options={[...PROJECT_STATUSES]} />
        </div>
        {list.loading && !list.data ? (
          <LoadingBlock />
        ) : list.error ? (
          <ErrorState error={list.error} onRetry={() => list.reload()} />
        ) : !list.data?.items.length ? (
          <EmptyState
            icon={<Clapperboard className="h-6 w-6" />}
            title={dq || channelId || status ? "No projects match your filters" : "No projects yet"}
            description={dq || channelId || status ? "Try clearing filters." : "Create a project to start generating a video."}
          />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Channel</th>
                  <th>Status</th>
                  <th>Format</th>
                  <th>Duration</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((p) => (
                  <tr key={p.id}>
                    <td className="max-w-xs">
                      <Link href={`/projects/${p.id}`} className="font-medium text-zinc-100 hover:text-accent-300">
                        {p.title}
                      </Link>
                      {p.topic && <p className="truncate text-xs text-zinc-500">{p.topic}</p>}
                    </td>
                    <td className="whitespace-nowrap">{channelMap.get(p.channel_id)?.name ?? "—"}</td>
                    <td>
                      <StatusBadge status={p.status} />
                    </td>
                    <td>
                      <Badge>{humanize(p.format)}</Badge>
                    </td>
                    <td className="tabular-nums">{fmtDuration(p.target_duration_sec)}</td>
                    <td className="whitespace-nowrap text-zinc-500">{fmtRelative(p.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </>
        )}
      </Card>
      {creating && channels.data && <NewProjectModal channels={channels.data.filter((c) => c.is_active)} defaultChannel={channelId} onClose={() => setCreating(false)} />}
    </>
  );
}

export default function ProjectsPage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <ProjectsInner />
    </Suspense>
  );
}
