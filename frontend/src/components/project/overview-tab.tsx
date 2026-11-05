"use client";

import { Save, Send, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { useToast } from "@/components/toast";
import { Button, Card, CardBody, CardHeader, ConfirmButton, FormError, Input, JsonEditor, KeyValue, Select, Textarea } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, humanize } from "@/lib/format";
import { PROJECT_STATUSES, VIDEO_FORMATS, type Channel, type Project, type ProjectStatus, type VideoFormat } from "@/lib/types";

export function OverviewTab({ project, channel, onChange }: { project: Project; channel?: Channel; onChange: (p: Project) => void }) {
  const { can } = useAuth();
  const toast = useToast();
  const router = useRouter();
  const editable = can("editor");
  const [title, setTitle] = useState(project.title);
  const [topic, setTopic] = useState(project.topic);
  const [format, setFormat] = useState<VideoFormat>(project.format);
  const [duration, setDuration] = useState(project.target_duration_sec);
  const [status, setStatus] = useState<ProjectStatus>(project.status);
  const [brief, setBrief] = useState<Record<string, unknown>>(project.brief ?? {});
  const [briefValid, setBriefValid] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [approvalNote, setApprovalNote] = useState("");
  const [requesting, setRequesting] = useState(false);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setFe({});
    try {
      const p = await api.projects.update(project.id, {
        title: title.trim(),
        topic,
        format,
        target_duration_sec: duration,
        status,
        brief,
      });
      onChange(p);
      toast.success("Project saved");
    } catch (err) {
      setError(err);
      if (err instanceof ApiError) setFe(err.fieldErrors);
    } finally {
      setBusy(false);
    }
  };

  const requestApproval = async () => {
    setRequesting(true);
    try {
      await api.approvals.request({ project_id: project.id, note: approvalNote });
      toast.success("Approval requested");
      setApprovalNote("");
      onChange(await api.projects.get(project.id));
    } catch (err) {
      toast.error(err);
    } finally {
      setRequesting(false);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader title="Brief" description="The inputs every AI agent receives." />
        <CardBody>
          <form onSubmit={save} className="space-y-4">
            <Input label="Title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} required disabled={!editable} error={fe.title} />
            <Textarea label="Topic" value={topic} onChange={(e) => setTopic(e.target.value)} rows={4} disabled={!editable} error={fe.topic} />
            <div className="grid gap-4 sm:grid-cols-3">
              <Select label="Format" value={format} onChange={(e) => setFormat(e.target.value as VideoFormat)} options={[...VIDEO_FORMATS]} disabled={!editable} />
              <Input
                label="Target duration (sec)"
                type="number"
                min={10}
                max={3600}
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
                disabled={!editable}
                error={fe.target_duration_sec}
              />
              <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value as ProjectStatus)} options={[...PROJECT_STATUSES]} disabled={!editable} />
            </div>
            <JsonEditor
              label="Additional brief (JSON)"
              value={brief}
              onChange={setBrief}
              onValidity={setBriefValid}
              rows={8}
              disabled={!editable}
              hint='Free-form context for the agents, e.g. {"must_include": ["…"], "avoid": ["…"], "sources": ["…"]}'
            />
            <FormError error={error} />
            {editable && (
              <div className="flex justify-end">
                <Button type="submit" variant="primary" loading={busy} disabled={!briefValid || !title.trim()} icon={<Save className="h-4 w-4" />}>
                  Save changes
                </Button>
              </div>
            )}
          </form>
        </CardBody>
      </Card>

      <div className="space-y-6">
        <Card>
          <CardHeader title="Details" />
          <CardBody>
            <KeyValue
              items={[
                ["Channel", channel?.name ?? "—"],
                ["Niche", channel?.niche || "—"],
                ["Tone", channel?.tone || "—"],
                ["Language", channel?.language?.toUpperCase() ?? "—"],
                ["Status", humanize(project.status)],
                ["Approval", channel?.require_approval ? "Required" : "Not required"],
                ["Created", fmtDate(project.created_at)],
                ["Updated", fmtDate(project.updated_at)],
              ]}
            />
          </CardBody>
        </Card>

        {editable && (
          <Card>
            <CardHeader title="Request review" description="Ask a reviewer to sign off on this project." />
            <CardBody className="space-y-3">
              <Textarea label="Note for reviewer" value={approvalNote} onChange={(e) => setApprovalNote(e.target.value)} maxLength={2000} rows={3} />
              <Button onClick={requestApproval} loading={requesting} icon={<Send className="h-4 w-4" />} className="w-full">
                Request approval
              </Button>
            </CardBody>
          </Card>
        )}

        {editable && (
          <Card className="border-rose-900/40">
            <CardHeader title="Danger zone" />
            <CardBody>
              <ConfirmButton
                buttonVariant="danger"
                size="sm"
                icon={<Trash2 className="h-4 w-4" />}
                title="Delete project"
                confirmLabel="Delete project"
                message={
                  <>
                    Permanently delete <strong>{project.title}</strong> with its assets, renders and agent history?
                  </>
                }
                onConfirm={async () => {
                  try {
                    await api.projects.remove(project.id);
                    toast.success("Project deleted");
                    router.replace("/projects");
                  } catch (e) {
                    toast.error(e);
                  }
                }}
              >
                Delete project
              </ConfirmButton>
            </CardBody>
          </Card>
        )}
      </div>
    </div>
  );
}
