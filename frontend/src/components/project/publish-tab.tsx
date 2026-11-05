"use client";

import { Link2, Send } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type FormEvent } from "react";
import { platformLabel } from "@/components/platform";
import { PublishFields, PublishJobRow } from "@/components/publish-job";
import { useToast } from "@/components/toast";
import { Button, Card, CardBody, CardHeader, EmptyState, ErrorState, FormError, LoadingBlock, Notice, Select } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, localInputToIso, parseTags } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import type { Channel, Privacy, Project, PublishJob, RenderJob, SocialAccount } from "@/lib/types";

function defaults(project: Project) {
  const o = project.optimization ?? {};
  const titles = Array.isArray(o.titles) ? (o.titles as unknown[]).filter((t): t is string => typeof t === "string") : [];
  const tags = Array.isArray(o.tags) ? (o.tags as unknown[]).filter((t): t is string => typeof t === "string") : [];
  const hashtags = Array.isArray(o.hashtags) ? (o.hashtags as unknown[]).filter((t): t is string => typeof t === "string") : [];
  const desc = typeof o.description === "string" ? o.description : "";
  return {
    title: titles[0] ?? project.title,
    description: hashtags.length ? `${desc}\n\n${hashtags.map((h) => (h.startsWith("#") ? h : `#${h}`)).join(" ")}`.trim() : desc,
    tags: tags.join(", "),
  };
}

function CreatePublishJob({
  project,
  channel,
  accounts,
  renders,
  onCreated,
}: {
  project: Project;
  channel?: Channel;
  accounts: SocialAccount[];
  renders: RenderJob[];
  onCreated: (j: PublishJob) => void;
}) {
  const toast = useToast();
  const d = useMemo(() => defaults(project), [project]);
  const sorted = useMemo(
    () => [...accounts].sort((a, b) => Number(b.channel_id === project.channel_id) - Number(a.channel_id === project.channel_id)),
    [accounts, project.channel_id],
  );
  const [accountId, setAccountId] = useState(sorted.find((a) => a.status === "active")?.id ?? sorted[0]?.id ?? "");
  const [renderId, setRenderId] = useState("");
  const [title, setTitle] = useState(d.title);
  const [description, setDescription] = useState(d.description);
  const [tags, setTags] = useState(d.tags);
  const [privacy, setPrivacy] = useState<Privacy>("private");
  const [when, setWhen] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const ok = renders.filter((r) => r.status === "succeeded");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setFe({});
    try {
      const j = await api.publishing.create({
        project_id: project.id,
        social_account_id: accountId,
        render_job_id: renderId || null,
        title: title.trim() || null,
        description,
        tags: parseTags(tags),
        privacy,
        scheduled_at: localInputToIso(when),
      });
      toast.success(j.status === "pending_approval" ? "Publish job created — awaiting approval" : "Publish job created");
      onCreated(j);
    } catch (err) {
      setError(err);
      if (err instanceof ApiError) setFe(err.fieldErrors);
    } finally {
      setBusy(false);
    }
  };

  if (!accounts.length) {
    return (
      <Card>
        <EmptyState
          icon={<Link2 className="h-6 w-6" />}
          title="No social accounts connected"
          description="Connect a YouTube or Instagram account to publish this video."
          action={
            <Link href="/accounts" className="inline-flex h-10 items-center rounded-md bg-accent-600 px-4 text-sm font-medium text-white hover:bg-accent-500">
              Connect an account
            </Link>
          }
        />
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader title="Schedule a post" description={channel?.require_approval ? "This channel requires reviewer approval before publishing." : undefined} />
      <CardBody>
        {!ok.length && (
          <div className="mb-4">
            <Notice tone="amber">No successful render yet. Render the video first — publishing uses the latest successful render by default.</Notice>
          </div>
        )}
        <form onSubmit={submit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Select
              label="Account"
              required
              value={accountId}
              onChange={(e) => setAccountId(e.target.value)}
              options={sorted.map((a) => ({
                value: a.id,
                label: `${platformLabel(a.platform)} · ${a.display_name}${a.channel_id === project.channel_id ? " (this channel)" : ""}${a.status !== "active" ? ` [${a.status}]` : ""}`,
              }))}
              error={fe.social_account_id}
            />
            <Select
              label="Render"
              value={renderId}
              onChange={(e) => setRenderId(e.target.value)}
              options={[{ value: "", label: "Latest successful render" }, ...ok.map((r) => ({ value: r.id, label: `${r.format} · ${fmtDate(r.finished_at ?? r.created_at)}` }))]}
              error={fe.render_job_id}
            />
          </div>
          <PublishFields
            title={title}
            setTitle={setTitle}
            description={description}
            setDescription={setDescription}
            tags={tags}
            setTags={setTags}
            privacy={privacy}
            setPrivacy={setPrivacy}
            when={when}
            setWhen={setWhen}
            fe={fe}
          />
          <FormError error={error} />
          <div className="flex justify-end">
            <Button type="submit" variant="primary" loading={busy} disabled={!accountId} icon={<Send className="h-4 w-4" />}>
              {when ? "Schedule" : "Queue for publishing"}
            </Button>
          </div>
        </form>
      </CardBody>
    </Card>
  );
}

export function PublishTab({ project, channel }: { project: Project; channel?: Channel }) {
  const { can, orgId } = useAuth();
  const accounts = useQuery(`accounts:${orgId}`, () => api.social.accounts());
  const renders = useQuery(`renders:${project.id}:ok`, () => api.renders.list({ project_id: project.id, status: "succeeded", limit: 50 }));
  const jobs = useQuery(`pubjobs:${project.id}`, () => api.publishing.list({ project_id: project.id, limit: 100 }), { interval: 10_000 });
  const accountName = useMemo(() => new Map((accounts.data ?? []).map((a) => [a.id, a.display_name])), [accounts.data]);

  const upsert = (j: PublishJob) =>
    jobs.setData((prev) =>
      prev
        ? prev.items.some((x) => x.id === j.id)
          ? { ...prev, items: prev.items.map((x) => (x.id === j.id ? j : x)) }
          : { ...prev, items: [j, ...prev.items], total: prev.total + 1 }
        : { items: [j], total: 1, limit: 100, offset: 0 },
    );

  return (
    <div className="grid gap-6 lg:grid-cols-5">
      <div className="lg:col-span-2">
        {can("editor") &&
          (accounts.loading || renders.loading ? (
            <LoadingBlock />
          ) : accounts.error ? (
            <Card>
              <ErrorState error={accounts.error} onRetry={() => accounts.reload()} />
            </Card>
          ) : (
            <CreatePublishJob project={project} channel={channel} accounts={accounts.data ?? []} renders={renders.data?.items ?? []} onCreated={upsert} />
          ))}
      </div>
      <Card className="lg:col-span-3">
        <CardHeader title="Publish jobs" description="Status, retries and history for this project's posts." />
        {jobs.loading && !jobs.data ? (
          <LoadingBlock />
        ) : jobs.error ? (
          <ErrorState error={jobs.error} onRetry={() => jobs.reload()} />
        ) : !jobs.data?.items.length ? (
          <EmptyState icon={<Send className="h-6 w-6" />} title="Not published yet" description="Create a publish job to schedule this video." />
        ) : (
          <div className="divide-y divide-zinc-800">
            {jobs.data.items.map((j) => (
              <PublishJobRow key={j.id} job={j} accountName={accountName.get(j.social_account_id)} onChange={upsert} />
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
