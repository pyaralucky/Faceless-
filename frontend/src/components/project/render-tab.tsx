"use client";

import { ArrowDown, ArrowUp, CheckCircle2, Film, Plus, RotateCcw, Square, Trash2, Wand2, XCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useToast } from "@/components/toast";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  EmptyState,
  ErrorState,
  FormError,
  Input,
  LoadingBlock,
  Notice,
  ProgressBar,
  Select,
  Spinner,
  StatusBadge,
  Table,
} from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cx, fmtDate, fmtRelative, humanize } from "@/lib/format";
import { useAssetBlobUrl, useQuery } from "@/lib/hooks";
import {
  MOTIONS,
  TRANSITIONS,
  VIDEO_FORMATS,
  type Asset,
  type Channel,
  type Motion,
  type Project,
  type RenderJob,
  type RenderSceneIn,
  type SubtitleStyle,
  type Transition,
  type VideoFormat,
} from "@/lib/types";

const ACTIVE = new Set(["queued", "running"]);

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

interface SceneRow extends RenderSceneIn {
  key: number;
}

let sceneSeq = 0;

function scenesFromStoryboard(project: Project, visuals: Asset[]): SceneRow[] {
  const board = Array.isArray(project.storyboard?.scenes) ? (project.storyboard.scenes as Record<string, unknown>[]) : [];
  return board.map((s, i) => ({
    key: ++sceneSeq,
    asset_id: visuals.length ? visuals[i % visuals.length].id : null,
    duration: typeof s.duration_sec === "number" ? s.duration_sec : 4,
    text: typeof s.narration === "string" ? s.narration : "",
    overlay_text: typeof s.overlay_text === "string" ? s.overlay_text.slice(0, 200) : "",
    transition: (TRANSITIONS as readonly string[]).includes(String(s.transition)) ? (s.transition as Transition) : "fade",
    transition_duration: 0.5,
    motion: (MOTIONS as readonly string[]).includes(String(s.motion)) ? (s.motion as Motion) : "zoom_in",
    background_color: "#101418",
  }));
}

function SceneEditor({ scenes, setScenes, visuals }: { scenes: SceneRow[]; setScenes: (f: (s: SceneRow[]) => SceneRow[]) => void; visuals: Asset[] }) {
  const update = (key: number, patch: Partial<SceneRow>) => setScenes((s) => s.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const move = (i: number, d: -1 | 1) =>
    setScenes((s) => {
      const j = i + d;
      if (j < 0 || j >= s.length) return s;
      const n = [...s];
      [n[i], n[j]] = [n[j], n[i]];
      return n;
    });
  const total = scenes.reduce((a, s) => a + (Number(s.duration) || 0), 0);
  const assetOptions = [{ value: "", label: "Solid color card" }, ...visuals.map((a) => ({ value: a.id, label: `${a.kind === "video" ? "Video" : "Image"}: ${a.filename}` }))];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-xs text-zinc-500">
        <span>
          {scenes.length} scene{scenes.length === 1 ? "" : "s"} · {total.toFixed(1)}s total
        </span>
        <Button
          size="xs"
          icon={<Plus className="h-3.5 w-3.5" />}
          onClick={() =>
            setScenes((s) => [...s, { key: ++sceneSeq, asset_id: null, duration: 4, text: "", overlay_text: "", transition: "fade", transition_duration: 0.5, motion: "zoom_in", background_color: "#101418" }])
          }
        >
          Add scene
        </Button>
      </div>
      {scenes.map((s, i) => (
        <div key={s.key} className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Scene {i + 1}</span>
            <div className="flex gap-1">
              <Button size="xs" variant="ghost" icon={<ArrowUp className="h-3.5 w-3.5" />} onClick={() => move(i, -1)} disabled={i === 0} aria-label="Move scene up" />
              <Button size="xs" variant="ghost" icon={<ArrowDown className="h-3.5 w-3.5" />} onClick={() => move(i, 1)} disabled={i === scenes.length - 1} aria-label="Move scene down" />
              <Button size="xs" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setScenes((x) => x.filter((r) => r.key !== s.key))} aria-label="Remove scene" />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
            <Select label="Visual" wrapperClassName="lg:col-span-2" value={s.asset_id ?? ""} onChange={(e) => update(s.key, { asset_id: e.target.value || null })} options={assetOptions} />
            <Input label="Duration (s)" type="number" step={0.1} min={0.3} max={600} value={s.duration} onChange={(e) => update(s.key, { duration: Number(e.target.value) })} />
            <Select label="Transition" value={s.transition} onChange={(e) => update(s.key, { transition: e.target.value as Transition })} options={[...TRANSITIONS]} />
            <Select label="Motion" value={s.motion} onChange={(e) => update(s.key, { motion: e.target.value as Motion })} options={[...MOTIONS]} />
            {!s.asset_id ? (
              <Input label="Card color" type="color" value={s.background_color} onChange={(e) => update(s.key, { background_color: e.target.value.toUpperCase() })} />
            ) : (
              <Input
                label="Transition (s)"
                type="number"
                step={0.1}
                min={0}
                max={3}
                value={s.transition_duration}
                onChange={(e) => update(s.key, { transition_duration: Number(e.target.value) })}
              />
            )}
            <Input label="Overlay text" wrapperClassName="sm:col-span-2 lg:col-span-2" maxLength={200} value={s.overlay_text} onChange={(e) => update(s.key, { overlay_text: e.target.value })} />
            <Input label="Narration / subtitle text" wrapperClassName="sm:col-span-2 lg:col-span-4" value={s.text} onChange={(e) => update(s.key, { text: e.target.value })} />
          </div>
        </div>
      ))}
    </div>
  );
}

function RenderForm({ project, channel, assets, onCreated }: { project: Project; channel?: Channel; assets: Asset[]; onCreated: (j: RenderJob) => void }) {
  const toast = useToast();
  const byKind = (k: string) => assets.filter((a) => a.kind === k);
  const visuals = assets.filter((a) => a.kind === "image" || a.kind === "video");
  const channelStyle = (channel?.branding?.subtitle_style ?? {}) as SubtitleStyle;
  const optimizationThumb = typeof project.optimization?.thumbnail_text === "string" ? project.optimization.thumbnail_text : "";

  const [format, setFormat] = useState<VideoFormat>(project.format);
  const [narration, setNarration] = useState(() => assets.filter((a) => a.kind === "narration").at(-1)?.id ?? "");
  const [music, setMusic] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [burn, setBurn] = useState(true);
  const [style, setStyle] = useState({ ...DEFAULT_STYLE, ...channelStyle });
  const [musicVolume, setMusicVolume] = useState(0.15);
  const [duck, setDuck] = useState(true);
  const [lufs, setLufs] = useState(-14);
  const [thumbText, setThumbText] = useState(optimizationThumb);
  const [customScenes, setCustomScenes] = useState(false);
  const [scenes, setScenesState] = useState<SceneRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [fe, setFe] = useState<Record<string, string>>({});
  const setScenes = useCallback((f: (s: SceneRow[]) => SceneRow[]) => setScenesState(f), []);
  const hasStoryboard = Array.isArray(project.storyboard?.scenes) && (project.storyboard.scenes as unknown[]).length > 0;

  const setS = (k: keyof SubtitleStyle, v: unknown) => setStyle((s) => ({ ...s, [k]: v }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setFe({});
    try {
      const job = await api.renders.create(project.id, {
        format,
        narration_asset_id: narration || null,
        music_asset_id: music || null,
        subtitle_asset_id: subtitle || null,
        burn_subtitles: burn,
        subtitle_style: style,
        music_volume: musicVolume,
        duck_music: duck,
        target_lufs: lufs,
        thumbnail_text: thumbText.trim() ? thumbText.trim() : null,
        scenes: customScenes ? scenes.map(({ key: _key, ...rest }) => rest) : null,
      });
      toast.success("Render queued");
      onCreated(job);
    } catch (err) {
      setError(err);
      if (err instanceof ApiError) setFe(err.fieldErrors);
    } finally {
      setBusy(false);
    }
  };

  const opt = (list: Asset[], none: string) => [{ value: "", label: none }, ...list.map((a) => ({ value: a.id, label: a.filename }))];

  return (
    <Card>
      <CardHeader title="New render" description="Compose scenes, narration, music and burned-in subtitles into a final MP4 + thumbnail." />
      <CardBody>
        <form onSubmit={submit} className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Select label="Format" value={format} onChange={(e) => setFormat(e.target.value as VideoFormat)} options={VIDEO_FORMATS.map((f) => ({ value: f, label: f === "vertical" ? "Vertical 1080×1920" : "Horizontal 1920×1080" }))} />
            <Select label="Narration" value={narration} onChange={(e) => setNarration(e.target.value)} options={opt(byKind("narration"), "No narration")} error={fe.narration_asset_id} />
            <Select label="Music" value={music} onChange={(e) => setMusic(e.target.value)} options={opt(byKind("music"), "No music")} error={fe.music_asset_id} />
            <Select label="Subtitles (SRT)" value={subtitle} onChange={(e) => setSubtitle(e.target.value)} options={opt(byKind("subtitle"), "Generate from scene text")} error={fe.subtitle_asset_id} />
          </div>

          <fieldset className="rounded-lg border border-zinc-800 p-4">
            <legend className="px-1 text-xs font-medium uppercase tracking-wide text-zinc-400">Audio</legend>
            <div className="grid gap-4 sm:grid-cols-3">
              <div className="space-y-1.5">
                <label htmlFor="music-volume" className="block text-xs font-medium uppercase tracking-wide text-zinc-400">
                  Music volume · {Math.round(musicVolume * 100)}%
                </label>
                <input id="music-volume" type="range" min={0} max={1} step={0.01} value={musicVolume} onChange={(e) => setMusicVolume(Number(e.target.value))} className="w-full accent-accent-500" />
              </div>
              <Input label="Target loudness (LUFS)" type="number" min={-30} max={-5} step={0.5} value={lufs} onChange={(e) => setLufs(Number(e.target.value))} error={fe.target_lufs} hint="-14 is the YouTube/Instagram norm" />
              <div className="flex items-end pb-2">
                <Checkbox label="Duck music under narration" checked={duck} onChange={setDuck} />
              </div>
            </div>
          </fieldset>

          <fieldset className="rounded-lg border border-zinc-800 p-4">
            <legend className="px-1 text-xs font-medium uppercase tracking-wide text-zinc-400">Subtitles</legend>
            <div className="mb-4">
              <Checkbox label="Burn subtitles into the video" checked={burn} onChange={setBurn} />
            </div>
            <div className={cx("grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-8", !burn && "pointer-events-none opacity-50")}>
              <Input label="Text" type="color" value={style.primary_color} onChange={(e) => setS("primary_color", e.target.value.toUpperCase())} error={fe["subtitle_style.primary_color"]} />
              <Input label="Outline" type="color" value={style.outline_color} onChange={(e) => setS("outline_color", e.target.value.toUpperCase())} error={fe["subtitle_style.outline_color"]} />
              <Input label="Highlight" type="color" value={style.highlight_color} onChange={(e) => setS("highlight_color", e.target.value.toUpperCase())} error={fe["subtitle_style.highlight_color"]} />
              <Select label="Position" value={style.position} onChange={(e) => setS("position", e.target.value)} options={["bottom", "center", "top"]} />
              <Input label="Size" type="number" min={0} max={200} value={style.font_size} onChange={(e) => setS("font_size", Number(e.target.value))} hint="0 = auto" />
              <Input label="Words/line" type="number" min={1} max={20} value={style.max_words_per_line} onChange={(e) => setS("max_words_per_line", Number(e.target.value))} />
              <div className="col-span-2 flex items-end gap-5 pb-2">
                <Checkbox label="Bold" checked={Boolean(style.bold)} onChange={(v) => setS("bold", v)} />
                <Checkbox label="Uppercase" checked={Boolean(style.uppercase)} onChange={(v) => setS("uppercase", v)} />
              </div>
            </div>
          </fieldset>

          <Input
            label="Thumbnail text"
            value={thumbText}
            onChange={(e) => setThumbText(e.target.value)}
            maxLength={120}
            placeholder={optimizationThumb || project.title.slice(0, 40)}
            hint="Leave blank to use the optimization agent's suggestion or the project title."
          />

          <fieldset className="rounded-lg border border-zinc-800 p-4">
            <legend className="px-1 text-xs font-medium uppercase tracking-wide text-zinc-400">Scenes</legend>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <Checkbox
                label="Customize scenes"
                hint={customScenes ? "Scenes below are sent explicitly." : "Default: derived from the storyboard, cycling through uploaded images/videos."}
                checked={customScenes}
                onChange={(v) => {
                  setCustomScenes(v);
                  if (v && scenes.length === 0) setScenesState(scenesFromStoryboard(project, visuals));
                }}
              />
              {customScenes && hasStoryboard && (
                <Button size="xs" icon={<Wand2 className="h-3.5 w-3.5" />} onClick={() => setScenesState(scenesFromStoryboard(project, visuals))}>
                  Reset from storyboard
                </Button>
              )}
            </div>
            {!customScenes && !hasStoryboard && (
              <Notice tone="amber">This project has no storyboard yet. Run the storyboard agent or customize scenes manually.</Notice>
            )}
            {customScenes && <SceneEditor scenes={scenes} setScenes={setScenes} visuals={visuals} />}
          </fieldset>

          <FormError error={error} />
          <div className="flex justify-end">
            <Button type="submit" variant="primary" icon={<Film className="h-4 w-4" />} loading={busy} disabled={customScenes ? scenes.length === 0 : !hasStoryboard}>
              Start render
            </Button>
          </div>
        </form>
      </CardBody>
    </Card>
  );
}

function Media({ projectId, job }: { projectId: string; job: RenderJob }) {
  const video = useAssetBlobUrl(projectId, job.output_asset_id);
  const thumb = useAssetBlobUrl(projectId, job.thumbnail_asset_id);
  const vertical = job.format === "vertical";
  return (
    <div className="grid gap-4 md:grid-cols-[2fr_1fr]">
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">Final video</p>
        <div className={cx("flex items-center justify-center overflow-hidden rounded-lg bg-black", vertical ? "aspect-[9/16] max-h-[560px]" : "aspect-video")}>
          {video.loading ? <Spinner /> : video.url ? <video src={video.url} controls className="h-full w-full" /> : <span className="text-xs text-zinc-500">Unavailable</span>}
        </div>
      </div>
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">Thumbnail</p>
        <div className="flex items-center justify-center overflow-hidden rounded-lg bg-zinc-950">
          {thumb.loading ? (
            <Spinner />
          ) : thumb.url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={thumb.url} alt="Render thumbnail" className="w-full" />
          ) : (
            <span className="p-6 text-xs text-zinc-500">Unavailable</span>
          )}
        </div>
      </div>
    </div>
  );
}

function RenderDetail({ jobId, initial, onUpdate }: { jobId: string; initial?: RenderJob; onUpdate: (j: RenderJob) => void }) {
  const { can } = useAuth();
  const toast = useToast();
  const [poll, setPoll] = useState(initial ? ACTIVE.has(initial.status) : true);
  const q = useQuery(`render:${jobId}`, () => api.renders.get(jobId), { interval: poll ? 2000 : false });
  const job = q.data ?? initial;

  useEffect(() => {
    if (!q.data) return;
    setPoll(ACTIVE.has(q.data.status));
    onUpdate(q.data);
  }, [q.data, onUpdate]);

  if (!job) return q.error ? <ErrorState error={q.error} /> : <LoadingBlock />;
  const checks = job.qc_report?.checks ?? [];
  const act = async (fn: () => Promise<RenderJob>, msg: string) => {
    try {
      const j = await fn();
      q.setData(j);
      setPoll(ACTIVE.has(j.status));
      toast.success(msg);
    } catch (e) {
      toast.error(e);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <StatusBadge status={job.status} />
        <Badge>{humanize(job.format)}</Badge>
        <span className="text-xs text-zinc-500">
          Attempt {job.attempts} · created {fmtDate(job.created_at)}
          {job.finished_at && ` · finished ${fmtRelative(job.finished_at)}`}
        </span>
        <div className="ml-auto flex gap-2">
          {can("editor") && ACTIVE.has(job.status) && (
            <Button size="sm" variant="danger" icon={<Square className="h-3.5 w-3.5" />} onClick={() => act(() => api.renders.cancel(job.id), "Render cancelled")}>
              Cancel
            </Button>
          )}
          {can("editor") && (job.status === "failed" || job.status === "cancelled") && (
            <Button size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => act(() => api.renders.resume(job.id), "Render resumed from checkpoint")}>
              Resume
            </Button>
          )}
        </div>
      </div>

      <div>
        <div className="mb-1.5 flex justify-between text-sm">
          <span className="text-zinc-300">{humanize(job.stage) || "Queued"}</span>
          <span className="tabular-nums text-zinc-400">{Math.round(job.progress)}%</span>
        </div>
        <ProgressBar value={job.progress} tone={job.status === "failed" ? "red" : job.status === "succeeded" ? "green" : "accent"} label="Render progress" />
      </div>

      {job.error && <Notice tone="red">{job.error}</Notice>}

      {checks.length > 0 && (
        <div>
          <div className="mb-2 flex items-center gap-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Quality checks</p>
            {job.qc_report.passed !== undefined && <Badge tone={job.qc_report.passed ? "green" : "red"}>{job.qc_report.passed ? "Passed" : "Failed"}</Badge>}
            {(job.qc_report.warnings?.length ?? 0) > 0 && <Badge tone="amber">{job.qc_report.warnings?.length} warning(s)</Badge>}
          </div>
          <Table className="rounded-lg border border-zinc-800">
            <thead>
              <tr>
                <th>Check</th>
                <th>Result</th>
                <th>Value</th>
                <th>Expected</th>
                <th>Severity</th>
              </tr>
            </thead>
            <tbody>
              {checks.map((c) => (
                <tr key={c.name}>
                  <td className="font-medium text-zinc-200">{humanize(c.name)}</td>
                  <td>
                    {c.passed ? (
                      <CheckCircle2 className="h-4 w-4 text-emerald-400" aria-label="Passed" />
                    ) : (
                      <XCircle className={cx("h-4 w-4", c.severity === "warning" ? "text-amber-400" : "text-rose-400")} aria-label="Failed" />
                    )}
                  </td>
                  <td className="font-mono text-xs">{c.value === null || c.value === undefined ? "—" : String(c.value)}</td>
                  <td className="font-mono text-xs text-zinc-500">{String(c.expected ?? "—")}</td>
                  <td>
                    <Badge tone={c.severity === "error" ? "red" : "amber"}>{c.severity}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      )}

      {job.status === "succeeded" && (job.output_asset_id || job.thumbnail_asset_id) && <Media projectId={job.project_id} job={job} />}
    </div>
  );
}

export function RenderTab({ project, channel, initialRenderId }: { project: Project; channel?: Channel; initialRenderId?: string | null }) {
  const { can } = useAuth();
  const assets = useQuery(`assets:${project.id}`, () => api.assets.list(project.id));
  const renders = useQuery(`renders:${project.id}`, () => api.renders.list({ project_id: project.id, limit: 50 }));
  const [selected, setSelected] = useState<string | null>(initialRenderId ?? null);
  const items = useMemo(() => renders.data?.items ?? [], [renders.data]);

  useEffect(() => {
    if (!selected && items.length) setSelected(items[0].id);
  }, [items, selected]);

  const setRenders = renders.setData;
  const reloadAssets = assets.reload;
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const onUpdate = useCallback(
    (j: RenderJob) => {
      const old = itemsRef.current.find((x) => x.id === j.id);
      if (!old || (old.updated_at === j.updated_at && old.progress === j.progress && old.status === j.status)) return;
      if (old.status !== j.status && j.status === "succeeded") void reloadAssets(true);
      setRenders((prev) => (prev ? { ...prev, items: prev.items.map((x) => (x.id === j.id ? j : x)) } : prev));
    },
    [setRenders, reloadAssets],
  );

  const selectedJob = items.find((j) => j.id === selected);

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader title="Render jobs" />
          {renders.loading && !renders.data ? (
            <LoadingBlock />
          ) : renders.error ? (
            <ErrorState error={renders.error} onRetry={() => renders.reload()} />
          ) : !items.length ? (
            <EmptyState icon={<Film className="h-6 w-6" />} title="No renders yet" description="Configure and start a render below." />
          ) : (
            <ul className="max-h-[520px] divide-y divide-zinc-800 overflow-y-auto">
              {items.map((j) => (
                <li key={j.id}>
                  <button onClick={() => setSelected(j.id)} className={cx("w-full space-y-2 px-5 py-3 text-left hover:bg-zinc-800/40", selected === j.id && "bg-accent-500/5")} aria-current={selected === j.id}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm text-zinc-200">
                        {humanize(j.format)} · {fmtRelative(j.created_at)}
                      </span>
                      <StatusBadge status={j.status} />
                    </div>
                    {ACTIVE.has(j.status) && <ProgressBar value={j.progress} label="Render progress" />}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader title="Render detail" description="Live progress (polled every 2s), QC report and preview." />
          <CardBody>
            {selected ? (
              <RenderDetail key={selected} jobId={selected} initial={selectedJob} onUpdate={onUpdate} />
            ) : (
              <EmptyState title="Select a render" />
            )}
          </CardBody>
        </Card>
      </div>
      {can("editor") &&
        (assets.loading && !assets.data ? (
          <LoadingBlock />
        ) : (
          <RenderForm
            project={project}
            channel={channel}
            assets={assets.data ?? []}
            onCreated={(j) => {
              renders.setData((prev) => (prev ? { ...prev, items: [j, ...prev.items], total: prev.total + 1 } : { items: [j], total: 1, limit: 50, offset: 0 }));
              setSelected(j.id);
            }}
          />
        ))}
    </div>
  );
}
