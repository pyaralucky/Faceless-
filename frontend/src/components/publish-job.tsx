"use client";

import { Ban, ChevronDown, ExternalLink, History, Pencil, RotateCcw, Send } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { PlatformIcon, platformLabel } from "@/components/platform";
import { useToast } from "@/components/toast";
import { Badge, Button, ConfirmButton, FormError, Input, Modal, ProgressBar, Select, StatusBadge, Textarea } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cx, fmtDate, fmtRelative, humanize, isoToLocalInput, localInputToIso, parseTags } from "@/lib/format";
import type { Privacy, PublishJob } from "@/lib/types";

export const EDITABLE_PUBLISH = new Set(["draft", "pending_approval", "scheduled", "failed"]);
const NOT_CANCELLABLE = new Set(["published", "uploading", "processing", "cancelled"]);
export const PRIVACY_OPTIONS: { value: Privacy; label: string }[] = [
  { value: "private", label: "Private" },
  { value: "unlisted", label: "Unlisted" },
  { value: "public", label: "Public" },
];

export function EditPublishJobModal({ job, onClose, onSaved }: { job: PublishJob; onClose: () => void; onSaved: (j: PublishJob) => void }) {
  const toast = useToast();
  const [title, setTitle] = useState(job.title);
  const [description, setDescription] = useState(job.description);
  const [tags, setTags] = useState(job.tags.join(", "));
  const [privacy, setPrivacy] = useState<Privacy>((job.privacy as Privacy) || "private");
  const [when, setWhen] = useState(isoToLocalInput(job.scheduled_at));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [fe, setFe] = useState<Record<string, string>>({});

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setFe({});
    try {
      const j = await api.publishing.update(job.id, {
        title,
        description,
        tags: parseTags(tags),
        privacy,
        scheduled_at: localInputToIso(when),
      });
      toast.success("Publish job updated");
      onSaved(j);
      onClose();
    } catch (err) {
      setError(err);
      if (err instanceof ApiError) setFe(err.fieldErrors);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Edit publish job"
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form="edit-publish" loading={busy}>
            Save
          </Button>
        </>
      }
    >
      <form id="edit-publish" onSubmit={submit} className="space-y-4">
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
      </form>
    </Modal>
  );
}

export function PublishFields(p: {
  title: string;
  setTitle: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
  tags: string;
  setTags: (v: string) => void;
  privacy: Privacy;
  setPrivacy: (v: Privacy) => void;
  when: string;
  setWhen: (v: string) => void;
  fe: Record<string, string>;
}) {
  const tz = typeof Intl !== "undefined" ? Intl.DateTimeFormat().resolvedOptions().timeZone : "local";
  return (
    <>
      <Input label="Title" value={p.title} onChange={(e) => p.setTitle(e.target.value)} maxLength={300} error={p.fe.title} hint={`${p.title.length}/300 · YouTube allows 100 characters`} />
      <Textarea label="Description" value={p.description} onChange={(e) => p.setDescription(e.target.value)} maxLength={5000} rows={5} error={p.fe.description} />
      <Input label="Tags" value={p.tags} onChange={(e) => p.setTags(e.target.value)} error={p.fe.tags} hint="Comma-separated" />
      <div className="grid gap-4 sm:grid-cols-2">
        <Select label="Privacy" value={p.privacy} onChange={(e) => p.setPrivacy(e.target.value as Privacy)} options={PRIVACY_OPTIONS} error={p.fe.privacy} />
        <Input
          label="Scheduled time"
          type="datetime-local"
          value={p.when}
          onChange={(e) => p.setWhen(e.target.value)}
          error={p.fe.scheduled_at}
          hint={p.when ? `Your local time (${tz}); sent as UTC ${localInputToIso(p.when)?.replace(".000Z", "Z")}` : "Empty = publish as soon as approved"}
        />
      </div>
    </>
  );
}

export function PublishJobRow({
  job,
  accountName,
  projectTitle,
  onChange,
  showProject,
}: {
  job: PublishJob;
  accountName?: string;
  projectTitle?: string;
  onChange: (j: PublishJob) => void;
  showProject?: boolean;
}) {
  const { can } = useAuth();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const editor = can("editor");

  const act = async (fn: () => Promise<PublishJob>, msg: string) => {
    try {
      const j = await fn();
      onChange(j);
      toast.success(msg);
    } catch (e) {
      toast.error(e);
    }
  };

  const busy = job.status === "uploading" || job.status === "processing";

  return (
    <div className="px-5 py-4">
      <div className="flex flex-wrap items-start gap-3">
        <PlatformIcon platform={job.platform} className="mt-0.5 h-5 w-5" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate font-medium text-zinc-100">{job.title || "Untitled"}</p>
            <StatusBadge status={job.status} />
            <Badge>{humanize(job.privacy)}</Badge>
          </div>
          <p className="mt-0.5 text-xs text-zinc-500">
            {platformLabel(job.platform)}
            {accountName ? ` · ${accountName}` : ""}
            {showProject && (
              <>
                {" · "}
                <Link href={`/projects/${job.project_id}?tab=publish`} className="text-accent-300 hover:text-accent-200">
                  {projectTitle ?? "Open project"}
                </Link>
              </>
            )}
          </p>
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-zinc-400">
            <span>Scheduled: {job.scheduled_at ? `${fmtDate(job.scheduled_at)} (${fmtRelative(job.scheduled_at)})` : "ASAP after approval"}</span>
            {job.next_attempt_at && job.status !== "published" && <span>Next attempt: {fmtDate(job.next_attempt_at)}</span>}
            <span>
              Attempts: {job.attempts}/{job.max_attempts}
            </span>
            {job.published_at && <span>Published: {fmtDate(job.published_at)}</span>}
          </div>
          {(busy || (job.upload_progress > 0 && job.upload_progress < 100)) && (
            <div className="mt-2 flex items-center gap-3">
              <ProgressBar value={job.upload_progress} className="max-w-xs" label="Upload progress" />
              <span className="text-xs tabular-nums text-zinc-400">{Math.round(job.upload_progress)}%</span>
            </div>
          )}
          {job.last_error && <p className="mt-2 rounded-md bg-rose-500/10 px-2 py-1 text-xs text-rose-300">{job.last_error}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-1">
          {job.external_url && (
            <a href={job.external_url} target="_blank" rel="noopener noreferrer" className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs text-accent-300 hover:bg-zinc-800">
              <ExternalLink className="h-3.5 w-3.5" /> View post
            </a>
          )}
          {editor && job.status === "scheduled" && (
            <Button size="xs" variant="primary" icon={<Send className="h-3.5 w-3.5" />} onClick={() => act(() => api.publishing.publishNow(job.id), "Publishing now")}>
              Publish now
            </Button>
          )}
          {editor && job.status === "failed" && (
            <Button size="xs" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => act(() => api.publishing.retry(job.id), "Retry scheduled")}>
              Retry
            </Button>
          )}
          {editor && EDITABLE_PUBLISH.has(job.status) && (
            <Button size="xs" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEditing(true)}>
              Edit
            </Button>
          )}
          {editor && !NOT_CANCELLABLE.has(job.status) && (
            <ConfirmButton
              size="xs"
              icon={<Ban className="h-3.5 w-3.5" />}
              title="Cancel publish job"
              confirmLabel="Cancel job"
              message="The video will not be published and any pending approval is cancelled."
              onConfirm={() => act(() => api.publishing.cancel(job.id), "Publish job cancelled")}
            >
              Cancel
            </ConfirmButton>
          )}
          <Button size="xs" variant="ghost" icon={<History className="h-3.5 w-3.5" />} onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            History
            <ChevronDown className={cx("h-3 w-3 transition-transform", open && "rotate-180")} />
          </Button>
        </div>
      </div>
      {open && (
        <ol className="ml-8 mt-3 space-y-1.5 border-l border-zinc-800 pl-4">
          {job.history.length === 0 && <li className="text-xs text-zinc-500">No history yet.</li>}
          {[...job.history].reverse().map((h, i) => {
            const { at, event, ...rest } = h;
            const extra = Object.entries(rest)
              .filter(([, v]) => v !== null && v !== undefined && v !== "")
              .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
              .join(" · ");
            return (
              <li key={i} className="text-xs">
                <span className="font-medium text-zinc-300">{humanize(String(event ?? "event"))}</span>
                <span className="ml-2 text-zinc-500">{fmtDate(typeof at === "string" ? at : null)}</span>
                {extra && <span className="ml-2 break-all text-zinc-500">{extra}</span>}
              </li>
            );
          })}
        </ol>
      )}
      {editing && <EditPublishJobModal job={job} onClose={() => setEditing(false)} onSaved={onChange} />}
    </div>
  );
}
