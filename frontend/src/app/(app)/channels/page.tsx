"use client";

import { Pencil, Plus, ShieldCheck, Trash2, Tv } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { useToast } from "@/components/toast";
import {
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmButton,
  EmptyState,
  ErrorState,
  FormError,
  Input,
  JsonEditor,
  LoadingBlock,
  Modal,
  PageHeader,
  Select,
  Textarea,
} from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { humanize } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { VIDEO_FORMATS, type Channel, type ChannelCreate, type SubtitleStyle, type VideoFormat } from "@/lib/types";

const DEFAULT_STYLE: Required<Pick<SubtitleStyle, "primary_color" | "outline_color" | "highlight_color" | "position" | "font_size" | "max_words_per_line" | "bold" | "uppercase">> = {
  primary_color: "#FFFFFF",
  outline_color: "#000000",
  highlight_color: "#FFD400",
  position: "bottom",
  font_size: 0,
  max_words_per_line: 5,
  bold: true,
  uppercase: false,
};

type FormState = Omit<ChannelCreate, "branding"> & {
  is_active: boolean;
  style: typeof DEFAULT_STYLE & Record<string, unknown>;
  extraBranding: Record<string, unknown>;
};

function toForm(ch?: Channel): FormState {
  const branding = { ...(ch?.branding ?? {}) };
  const style = { ...DEFAULT_STYLE, ...((branding.subtitle_style as SubtitleStyle | undefined) ?? {}) };
  delete branding.subtitle_style;
  return {
    name: ch?.name ?? "",
    niche: ch?.niche ?? "",
    description: ch?.description ?? "",
    language: ch?.language ?? "en",
    tone: ch?.tone ?? "informative, engaging",
    target_audience: ch?.target_audience ?? "",
    default_format: ch?.default_format ?? "vertical",
    require_approval: ch?.require_approval ?? true,
    is_active: ch?.is_active ?? true,
    style: style as FormState["style"],
    extraBranding: branding,
  };
}

function ChannelModal({ open, channel, onClose, onSaved }: { open: boolean; channel?: Channel; onClose: () => void; onSaved: (c: Channel) => void }) {
  const toast = useToast();
  const [form, setForm] = useState<FormState>(() => toForm(channel));
  const [jsonValid, setJsonValid] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [fe, setFe] = useState<Record<string, string>>({});

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setForm((f) => ({ ...f, [k]: v }));
  const setStyle = (k: string, v: unknown) => setForm((f) => ({ ...f, style: { ...f.style, [k]: v } }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setFe({});
    const { style, extraBranding, is_active, ...rest } = form;
    const payload = { ...rest, branding: { ...extraBranding, subtitle_style: style } };
    try {
      const saved = channel ? await api.channels.update(channel.id, { ...payload, is_active }) : await api.channels.create(payload);
      toast.success(channel ? "Channel updated" : "Channel created");
      onSaved(saved);
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
      open={open}
      onClose={onClose}
      size="lg"
      title={channel ? `Edit ${channel.name}` : "New channel"}
      description="A channel defines the niche, voice and branding used by the AI agents and renderer."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form="channel-form" loading={busy} disabled={!form.name.trim() || !jsonValid}>
            {channel ? "Save changes" : "Create channel"}
          </Button>
        </>
      }
    >
      <form id="channel-form" onSubmit={submit} className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Name" value={form.name} onChange={(e) => set("name", e.target.value)} required maxLength={120} error={fe.name} />
          <Input label="Niche" value={form.niche} onChange={(e) => set("niche", e.target.value)} maxLength={200} placeholder="Space history, personal finance…" error={fe.niche} />
          <Input label="Language" value={form.language} onChange={(e) => set("language", e.target.value)} maxLength={10} hint="ISO code, e.g. en, es, de" error={fe.language} />
          <Input label="Tone" value={form.tone} onChange={(e) => set("tone", e.target.value)} maxLength={200} error={fe.tone} />
          <Input
            label="Target audience"
            value={form.target_audience}
            onChange={(e) => set("target_audience", e.target.value)}
            maxLength={300}
            wrapperClassName="sm:col-span-2"
            error={fe.target_audience}
          />
          <Textarea label="Description" value={form.description} onChange={(e) => set("description", e.target.value)} wrapperClassName="sm:col-span-2" error={fe.description} />
          <Select
            label="Default format"
            value={form.default_format}
            onChange={(e) => set("default_format", e.target.value as VideoFormat)}
            options={VIDEO_FORMATS.map((f) => ({ value: f, label: f === "vertical" ? "Vertical 9:16 (Shorts / Reels)" : "Horizontal 16:9" }))}
          />
          <div className="flex flex-col justify-end gap-3 pb-1">
            <Checkbox label="Require approval before publishing" checked={form.require_approval} onChange={(v) => set("require_approval", v)} />
            {channel && <Checkbox label="Active" checked={form.is_active} onChange={(v) => set("is_active", v)} />}
          </div>
        </div>

        <fieldset className="rounded-lg border border-zinc-800 p-4">
          <legend className="px-1 text-xs font-medium uppercase tracking-wide text-zinc-400">Branding · subtitle style</legend>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Input label="Text" type="color" value={form.style.primary_color} onChange={(e) => setStyle("primary_color", e.target.value.toUpperCase())} />
            <Input label="Outline" type="color" value={form.style.outline_color} onChange={(e) => setStyle("outline_color", e.target.value.toUpperCase())} />
            <Input label="Highlight" type="color" value={form.style.highlight_color} onChange={(e) => setStyle("highlight_color", e.target.value.toUpperCase())} />
            <Select label="Position" value={form.style.position} onChange={(e) => setStyle("position", e.target.value)} options={["bottom", "center", "top"]} />
            <Input
              label="Font size"
              type="number"
              min={0}
              max={200}
              value={form.style.font_size}
              onChange={(e) => setStyle("font_size", Number(e.target.value))}
              hint="0 = auto"
            />
            <Input
              label="Words / line"
              type="number"
              min={1}
              max={20}
              value={form.style.max_words_per_line}
              onChange={(e) => setStyle("max_words_per_line", Number(e.target.value))}
            />
            <div className="col-span-2 flex items-end gap-6 pb-2">
              <Checkbox label="Bold" checked={Boolean(form.style.bold)} onChange={(v) => setStyle("bold", v)} />
              <Checkbox label="Uppercase" checked={Boolean(form.style.uppercase)} onChange={(v) => setStyle("uppercase", v)} />
            </div>
          </div>
          <div className="mt-4">
            <JsonEditor
              label="Additional branding (JSON)"
              rows={5}
              value={form.extraBranding}
              onChange={(v) => set("extraBranding", v)}
              onValidity={setJsonValid}
              hint='Any extra keys, e.g. {"scene_colors": ["#14213D", "#1B263B"], "logo_text": "…"}. subtitle_style is managed above.'
            />
          </div>
        </fieldset>
        <FormError error={error} />
      </form>
    </Modal>
  );
}

export default function ChannelsPage() {
  const { orgId, can } = useAuth();
  const toast = useToast();
  const [includeInactive, setIncludeInactive] = useState(false);
  const { data, error, loading, reload } = useQuery(`channels:${orgId}:${includeInactive}`, () => api.channels.list(includeInactive));
  const [editing, setEditing] = useState<Channel | null>(null);
  const [creating, setCreating] = useState(false);

  return (
    <>
      <PageHeader
        title="Channels"
        description="Each channel has its own niche, voice, branding and connected social accounts."
        actions={
          <>
            <Checkbox label="Show inactive" checked={includeInactive} onChange={setIncludeInactive} />
            {can("editor") && (
              <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
                New channel
              </Button>
            )}
          </>
        }
      />

      {loading && !data ? (
        <LoadingBlock />
      ) : error ? (
        <Card>
          <ErrorState error={error} onRetry={() => reload()} />
        </Card>
      ) : !data?.length ? (
        <Card>
          <EmptyState
            icon={<Tv className="h-6 w-6" />}
            title="No channels yet"
            description="Create your first channel to define the niche and style of your videos."
            action={
              can("editor") && (
                <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
                  New channel
                </Button>
              )
            }
          />
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.map((ch) => (
            <Card key={ch.id} className="flex flex-col p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="truncate font-semibold text-zinc-100">{ch.name}</h3>
                  <p className="truncate text-sm text-zinc-400">{ch.niche || "No niche set"}</p>
                </div>
                <div className="flex shrink-0 gap-1">
                  {can("editor") && (
                    <Button size="xs" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEditing(ch)} aria-label={`Edit ${ch.name}`} />
                  )}
                  {can("admin") && (
                    <ConfirmButton
                      size="xs"
                      icon={<Trash2 className="h-3.5 w-3.5" />}
                      aria-label={`Delete ${ch.name}`}
                      title="Delete channel"
                      confirmLabel="Delete"
                      message={
                        <>
                          Delete <strong>{ch.name}</strong>? Projects in this channel may be removed or orphaned. This cannot be undone.
                        </>
                      }
                      onConfirm={async () => {
                        try {
                          await api.channels.remove(ch.id);
                          toast.success("Channel deleted");
                          await reload(true);
                        } catch (e) {
                          toast.error(e);
                        }
                      }}
                    />
                  )}
                </div>
              </div>
              {ch.description && <p className="mt-3 line-clamp-3 text-sm text-zinc-400">{ch.description}</p>}
              <div className="mt-4 flex flex-wrap gap-1.5">
                <Badge tone="accent">{humanize(ch.default_format)}</Badge>
                <Badge>{ch.language.toUpperCase()}</Badge>
                {ch.require_approval && (
                  <Badge tone="amber">
                    <ShieldCheck className="h-3 w-3" /> Approval required
                  </Badge>
                )}
                {!ch.is_active && <Badge tone="red">Inactive</Badge>}
              </div>
              <div className="mt-auto flex items-center justify-between pt-4 text-sm">
                <span className="text-zinc-500">
                  {ch.project_count} project{ch.project_count === 1 ? "" : "s"}
                </span>
                <Link href={`/projects?channel_id=${ch.id}`} className="text-accent-300 hover:text-accent-200">
                  View projects →
                </Link>
              </div>
            </Card>
          ))}
        </div>
      )}

      {creating && <ChannelModal open onClose={() => setCreating(false)} onSaved={() => reload(true)} />}
      {editing && <ChannelModal key={editing.id} open channel={editing} onClose={() => setEditing(null)} onSaved={() => reload(true)} />}
    </>
  );
}
