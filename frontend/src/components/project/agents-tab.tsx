"use client";

import { Bot, Code2, Eye, Play, Save, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
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
  JsonEditor,
  LoadingBlock,
  Notice,
  StatusBadge,
  Table,
  Tabs,
  Textarea,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cx, fmtDate, fmtMs, fmtNumber, fmtRelative, fmtUsd, humanize, isEmptyObject } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { AGENT_NAMES, type AgentName, type AgentRun, type Project } from "@/lib/types";
import { AgentOutput } from "./outputs";

const ACTIVE = new Set(["queued", "running"]);

function StartRun({ projectId, onStarted }: { projectId: string; onStarted: (run: AgentRun) => void }) {
  const toast = useToast();
  const [selected, setSelected] = useState<AgentName[]>([]);
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);

  const toggle = (a: AgentName, on: boolean) => setSelected((s) => (on ? AGENT_NAMES.filter((x) => x === a || s.includes(x)) : s.filter((x) => x !== a)));

  const start = async () => {
    setBusy(true);
    try {
      const run = await api.agentRuns.start(projectId, { agents: selected, instructions: instructions.trim() });
      toast.success(selected.length ? `Started ${selected.length} agent(s)` : "Started full pipeline");
      setInstructions("");
      onStarted(run);
    } catch (e) {
      toast.error(e, "Could not start run");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader title="Start an agent run" description="Leave all unchecked to run the full pipeline in order." />
      <CardBody className="space-y-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {AGENT_NAMES.map((a) => (
            <Checkbox key={a} label={humanize(a)} checked={selected.includes(a)} onChange={(v) => toggle(a, v)} />
          ))}
        </div>
        <Textarea
          label="Extra instructions"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          maxLength={4000}
          rows={3}
          placeholder="e.g. Make the hook more provocative; cite NASA where possible."
        />
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-zinc-500">{selected.length ? `Running: ${selected.map(humanize).join(" → ")}` : "Running: full pipeline"}</p>
          <Button variant="primary" onClick={start} loading={busy} icon={<Play className="h-4 w-4" />}>
            Start run
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

function RunDetail({ runId, onFinished }: { runId: string; onFinished: () => void }) {
  const { can } = useAuth();
  const toast = useToast();
  const [polling, setPolling] = useState(true);
  const run = useQuery(`run:${runId}`, () => api.agentRuns.get(runId), { interval: polling ? 2000 : false });
  const prevStatus = useRef<string | null>(null);

  useEffect(() => {
    const st = run.data?.status;
    if (!st) return;
    const active = ACTIVE.has(st);
    setPolling(active);
    if (prevStatus.current && ACTIVE.has(prevStatus.current) && !active) onFinished();
    prevStatus.current = st;
  }, [run.data?.status, onFinished]);

  if (run.loading && !run.data) return <LoadingBlock label="Loading run…" />;
  if (run.error && !run.data) return <ErrorState error={run.error} onRetry={() => run.reload()} />;
  const d = run.data;
  if (!d) return null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <StatusBadge status={d.status} />
        <span className="text-sm text-zinc-400">{d.agents.length ? d.agents.map(humanize).join(" → ") : "Full pipeline"}</span>
        <span className="ml-auto flex flex-wrap items-center gap-3 text-xs text-zinc-500">
          <span>{fmtNumber(d.prompt_tokens + d.completion_tokens)} tokens</span>
          <span>{fmtUsd(d.cost_usd)}</span>
          <span>Started {fmtDate(d.started_at)}</span>
          {d.finished_at && <span>Finished {fmtDate(d.finished_at)}</span>}
        </span>
        {ACTIVE.has(d.status) && can("editor") && (
          <Button
            size="sm"
            variant="danger"
            icon={<Square className="h-3.5 w-3.5" />}
            onClick={async () => {
              try {
                await api.agentRuns.cancel(d.id);
                toast.info("Cancellation requested");
                await run.reload(true);
              } catch (e) {
                toast.error(e);
              }
            }}
          >
            Cancel
          </Button>
        )}
      </div>
      {d.error && <Notice tone="red">{d.error}</Notice>}
      {typeof d.input?.instructions === "string" && d.input.instructions && (
        <p className="text-xs text-zinc-500">
          Instructions: <span className="text-zinc-400">{d.input.instructions}</span>
        </p>
      )}
      {d.steps.length === 0 ? (
        <p className="text-sm text-zinc-500">{ACTIVE.has(d.status) ? "Waiting for the first agent to start…" : "No steps recorded."}</p>
      ) : (
        <Table>
          <thead>
            <tr>
              <th>Agent</th>
              <th>Attempt</th>
              <th>Status</th>
              <th>Provider / model</th>
              <th className="text-right">Tokens</th>
              <th className="text-right">Cost</th>
              <th className="text-right">Latency</th>
              <th>Error</th>
            </tr>
          </thead>
          <tbody>
            {d.steps.map((s) => (
              <tr key={s.id}>
                <td className="font-medium text-zinc-200">{humanize(s.agent_name)}</td>
                <td className="tabular-nums">{s.attempt}</td>
                <td>
                  <StatusBadge status={s.status} />
                </td>
                <td className="whitespace-nowrap text-zinc-400">
                  {s.provider ?? "—"}
                  {s.model ? ` / ${s.model}` : ""}
                </td>
                <td className="text-right tabular-nums" title={`${s.prompt_tokens} prompt + ${s.completion_tokens} completion`}>
                  {fmtNumber(s.prompt_tokens + s.completion_tokens)}
                </td>
                <td className="text-right tabular-nums">{fmtUsd(s.cost_usd)}</td>
                <td className="text-right tabular-nums">{fmtMs(s.latency_ms)}</td>
                <td className="max-w-xs text-xs text-rose-300">{s.error ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </div>
  );
}

function Outputs({ project, onChange }: { project: Project; onChange: (p: Project) => void }) {
  const { can } = useAuth();
  const toast = useToast();
  const [tab, setTab] = useState<AgentName>("script");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [valid, setValid] = useState(true);
  const [saving, setSaving] = useState(false);
  const editableTab = tab === "script" || tab === "storyboard";

  useEffect(() => {
    setEditing(false);
  }, [tab]);

  const startEdit = () => {
    setDraft((project[tab] as Record<string, unknown>) ?? {});
    setValid(true);
    setEditing(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      const p = await api.projects.update(project.id, { [tab]: draft });
      onChange(p);
      toast.success(`${humanize(tab)} saved`);
      setEditing(false);
    } catch (e) {
      toast.error(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title="Agent outputs"
        description="Latest output from each agent, stored on the project."
        actions={
          editableTab &&
          can("editor") &&
          (editing ? (
            <>
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                Cancel
              </Button>
              <Button size="sm" variant="primary" icon={<Save className="h-4 w-4" />} loading={saving} disabled={!valid} onClick={save}>
                Save {humanize(tab).toLowerCase()}
              </Button>
            </>
          ) : (
            <Button size="sm" icon={<Code2 className="h-4 w-4" />} onClick={startEdit}>
              Edit JSON
            </Button>
          ))
        }
      />
      <div className="px-5 pt-2">
        <Tabs
          value={tab}
          onChange={setTab}
          tabs={AGENT_NAMES.map((a) => ({
            value: a,
            label: (
              <span className="flex items-center gap-1.5">
                {humanize(a)}
                <span className={cx("h-1.5 w-1.5 rounded-full", isEmptyObject(project[a]) ? "bg-zinc-700" : "bg-emerald-400")} aria-hidden />
              </span>
            ),
          }))}
        />
      </div>
      <CardBody>
        {editing ? (
          <JsonEditor value={draft} onChange={setDraft} onValidity={setValid} rows={24} hint="Edits replace the stored output. Rendering derives scenes from storyboard.scenes[]." />
        ) : (
          <AgentOutput agent={tab} data={project[tab]} />
        )}
      </CardBody>
    </Card>
  );
}

export function AgentsTab({ project, onChange, initialRunId }: { project: Project; onChange: (p: Project) => void; initialRunId?: string | null }) {
  const { can } = useAuth();
  const [listPoll, setListPoll] = useState(false);
  const runs = useQuery(`runs:${project.id}`, () => api.agentRuns.list({ project_id: project.id, limit: 25 }), { interval: listPoll ? 5000 : false });
  const [selected, setSelected] = useState<string | null>(initialRunId ?? null);
  const anyActive = Boolean(runs.data?.items.some((r) => ACTIVE.has(r.status)));

  useEffect(() => {
    if (!selected && runs.data?.items.length) setSelected(runs.data.items[0].id);
  }, [runs.data, selected]);

  useEffect(() => setListPoll(anyActive), [anyActive]);

  const reloadRuns = runs.reload;
  const onFinished = useCallback(async () => {
    await reloadRuns(true);
    try {
      onChange(await api.projects.get(project.id));
    } catch {
      /* project refresh is best-effort */
    }
  }, [reloadRuns, onChange, project.id]);

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-1">
          {can("editor") && (
            <StartRun
              projectId={project.id}
              onStarted={(r) => {
                runs.setData((prev) => (prev ? { ...prev, items: [r, ...prev.items], total: prev.total + 1 } : { items: [r], total: 1, limit: 25, offset: 0 }));
                setSelected(r.id);
              }}
            />
          )}
          <Card>
            <CardHeader title="Run history" />
            {runs.loading && !runs.data ? (
              <LoadingBlock />
            ) : runs.error ? (
              <ErrorState error={runs.error} onRetry={() => runs.reload()} />
            ) : !runs.data?.items.length ? (
              <EmptyState icon={<Bot className="h-6 w-6" />} title="No runs yet" />
            ) : (
              <ul className="max-h-[420px] divide-y divide-zinc-800 overflow-y-auto">
                {runs.data.items.map((r) => (
                  <li key={r.id}>
                    <button
                      onClick={() => setSelected(r.id)}
                      className={cx("flex w-full items-center gap-3 px-5 py-3 text-left hover:bg-zinc-800/40", selected === r.id && "bg-accent-500/5")}
                      aria-current={selected === r.id}
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm text-zinc-200">{r.agents.length ? r.agents.map(humanize).join(", ") : "Full pipeline"}</p>
                        <p className="text-xs text-zinc-500">
                          {fmtRelative(r.created_at)} · {fmtNumber(r.prompt_tokens + r.completion_tokens)} tok · {fmtUsd(r.cost_usd)}
                        </p>
                      </div>
                      <StatusBadge status={r.status} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <Card className="lg:col-span-2">
          <CardHeader
            title="Execution log"
            description="Per-agent steps with provider, tokens, cost and latency. Live-updates every 2s while running."
            actions={selected && <Badge tone="zinc">{selected.slice(0, 8)}</Badge>}
          />
          <CardBody>
            {selected ? <RunDetail key={selected} runId={selected} onFinished={onFinished} /> : <EmptyState icon={<Eye className="h-6 w-6" />} title="Select a run to inspect it" />}
          </CardBody>
        </Card>
      </div>
      <Outputs project={project} onChange={onChange} />
    </div>
  );
}
