"use client";

import { Download, Eye, FileAudio, FileImage, FileText, FileVideo, Trash2, Upload } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { useToast } from "@/components/toast";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ConfirmButton,
  EmptyState,
  ErrorState,
  LoadingBlock,
  Modal,
  Select,
  Table,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtBytes, fmtDuration, fmtRelative, humanize } from "@/lib/format";
import { downloadAsset, useAssetBlobUrl, useQuery } from "@/lib/hooks";
import { ASSET_KINDS, UPLOADABLE_ASSET_KINDS, type Asset, type AssetKind, type UploadableAssetKind } from "@/lib/types";

const ACCEPT: Record<UploadableAssetKind, string> = {
  image: "image/*",
  video: "video/*",
  narration: "audio/*",
  music: "audio/*",
  subtitle: ".srt,.vtt,.ass,text/plain,application/x-subrip",
};

export function AssetIcon({ kind, className = "h-4 w-4" }: { kind: string; className?: string }) {
  if (kind === "image" || kind === "thumbnail") return <FileImage className={`${className} text-sky-400`} />;
  if (kind === "video" || kind === "render") return <FileVideo className={`${className} text-fuchsia-400`} />;
  if (kind === "narration" || kind === "music") return <FileAudio className={`${className} text-emerald-400`} />;
  return <FileText className={`${className} text-zinc-400`} />;
}

function Preview({ asset, onClose }: { asset: Asset; onClose: () => void }) {
  const { url, error, loading } = useAssetBlobUrl(asset.project_id, asset.id);
  const mime = asset.mime_type || "";
  return (
    <Modal open onClose={onClose} title={asset.filename} description={`${humanize(asset.kind)} · ${fmtBytes(asset.size_bytes)}`} size="lg">
      {loading ? (
        <LoadingBlock />
      ) : error ? (
        <ErrorState error={error} />
      ) : url ? (
        mime.startsWith("image/") ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url} alt={asset.filename} className="mx-auto max-h-[70vh] rounded-lg" />
        ) : mime.startsWith("video/") ? (
          <video src={url} controls className="mx-auto max-h-[70vh] w-full rounded-lg bg-black" />
        ) : mime.startsWith("audio/") ? (
          <audio src={url} controls className="w-full" />
        ) : (
          <TextPreview url={url} />
        )
      ) : null}
    </Modal>
  );
}

function TextPreview({ url }: { url: string }) {
  const q = useQuery(`text:${url}`, () => fetch(url).then((r) => r.text()));
  if (q.loading) return <LoadingBlock />;
  return <pre className="max-h-[60vh] overflow-auto rounded-lg bg-zinc-950 p-4 font-mono text-xs text-zinc-300">{q.data}</pre>;
}

export function AssetsTab({ projectId }: { projectId: string }) {
  const { can } = useAuth();
  const toast = useToast();
  const [kindFilter, setKindFilter] = useState<AssetKind | "">("");
  const assets = useQuery(`assets:${projectId}`, () => api.assets.list(projectId));
  const [uploadKind, setUploadKind] = useState<UploadableAssetKind>("image");
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState<string | null>(null);
  const [preview, setPreview] = useState<Asset | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const upload = async (e: FormEvent) => {
    e.preventDefault();
    if (!files.length) return;
    let ok = 0;
    for (const f of files) {
      setUploading(f.name);
      try {
        const a = await api.assets.upload(projectId, uploadKind, f, f.name);
        assets.setData((prev) => [...(prev ?? []), a]);
        ok++;
      } catch (err) {
        toast.error(err, `Upload failed: ${f.name}`);
      }
    }
    setUploading(null);
    if (ok) toast.success(`Uploaded ${ok} file${ok === 1 ? "" : "s"}`);
    setFiles([]);
    if (inputRef.current) inputRef.current.value = "";
  };

  const items = (assets.data ?? []).filter((a) => !kindFilter || a.kind === kindFilter);

  return (
    <div className="space-y-6">
      {can("editor") && (
        <Card>
          <CardHeader title="Upload assets" description="Images & video clips for scenes, narration & music audio, SRT subtitles." />
          <CardBody>
            <form onSubmit={upload} className="grid gap-4 sm:grid-cols-[180px_1fr_auto] sm:items-end">
              <Select label="Kind" value={uploadKind} onChange={(e) => setUploadKind(e.target.value as UploadableAssetKind)} options={[...UPLOADABLE_ASSET_KINDS]} />
              <div className="space-y-1.5">
                <label htmlFor="asset-file" className="block text-xs font-medium uppercase tracking-wide text-zinc-400">
                  Files
                </label>
                <input
                  id="asset-file"
                  ref={inputRef}
                  type="file"
                  multiple
                  accept={ACCEPT[uploadKind]}
                  onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
                  className="block w-full text-sm text-zinc-400 file:mr-3 file:rounded-md file:border-0 file:bg-zinc-800 file:px-3 file:py-2 file:text-sm file:text-zinc-200 hover:file:bg-zinc-700"
                />
              </div>
              <Button type="submit" variant="primary" icon={<Upload className="h-4 w-4" />} loading={Boolean(uploading)} disabled={!files.length}>
                {uploading ? `Uploading ${uploading.slice(0, 18)}…` : "Upload"}
              </Button>
            </form>
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader
          title="Project assets"
          description={assets.data ? `${assets.data.length} file${assets.data.length === 1 ? "" : "s"}` : undefined}
          actions={
            <Select
              aria-label="Filter assets by kind"
              value={kindFilter}
              onChange={(e) => setKindFilter(e.target.value as AssetKind | "")}
              placeholder="All kinds"
              options={[...ASSET_KINDS]}
              className="h-8 w-40"
            />
          }
        />
        {assets.loading && !assets.data ? (
          <LoadingBlock />
        ) : assets.error ? (
          <ErrorState error={assets.error} onRetry={() => assets.reload()} />
        ) : !items.length ? (
          <EmptyState title="No assets" description="Uploaded files and render outputs appear here." />
        ) : (
          <Table>
            <thead>
              <tr>
                <th>File</th>
                <th>Kind</th>
                <th>Size</th>
                <th>Media</th>
                <th>Added</th>
                <th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id}>
                  <td className="max-w-xs">
                    <div className="flex items-center gap-2">
                      <AssetIcon kind={a.kind} />
                      <span className="truncate text-zinc-200" title={a.filename}>
                        {a.filename}
                      </span>
                    </div>
                    <p className="pl-6 text-xs text-zinc-500">{a.mime_type}</p>
                  </td>
                  <td>
                    <Badge tone={a.kind === "render" || a.kind === "thumbnail" ? "accent" : "zinc"}>{humanize(a.kind)}</Badge>
                  </td>
                  <td className="tabular-nums">{fmtBytes(a.size_bytes)}</td>
                  <td className="whitespace-nowrap text-xs text-zinc-400">
                    {[a.width && a.height ? `${a.width}×${a.height}` : null, a.duration_sec ? fmtDuration(a.duration_sec) : null].filter(Boolean).join(" · ") || "—"}
                  </td>
                  <td className="whitespace-nowrap text-zinc-500">{fmtRelative(a.created_at)}</td>
                  <td>
                    <div className="flex justify-end gap-1">
                      <Button size="xs" variant="ghost" icon={<Eye className="h-3.5 w-3.5" />} onClick={() => setPreview(a)} aria-label={`Preview ${a.filename}`} />
                      <Button
                        size="xs"
                        variant="ghost"
                        icon={<Download className="h-3.5 w-3.5" />}
                        aria-label={`Download ${a.filename}`}
                        onClick={() => downloadAsset(projectId, a.id, a.filename).catch((e) => toast.error(e))}
                      />
                      {can("editor") && (
                        <ConfirmButton
                          size="xs"
                          icon={<Trash2 className="h-3.5 w-3.5" />}
                          aria-label={`Delete ${a.filename}`}
                          title="Delete asset"
                          confirmLabel="Delete"
                          message={
                            <>
                              Delete <strong>{a.filename}</strong>? Renders referencing it can no longer be resumed.
                            </>
                          }
                          onConfirm={async () => {
                            try {
                              await api.assets.remove(projectId, a.id);
                              assets.setData((prev) => (prev ?? []).filter((x) => x.id !== a.id));
                              toast.success("Asset deleted");
                            } catch (e) {
                              toast.error(e);
                            }
                          }}
                        />
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {preview && <Preview asset={preview} onClose={() => setPreview(null)} />}
    </div>
  );
}
