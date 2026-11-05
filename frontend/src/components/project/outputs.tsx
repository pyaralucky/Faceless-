"use client";

import type { ReactElement, ReactNode } from "react";
import { Badge, Chips, EmptyState, KeyValue, StatusBadge, Table } from "@/components/ui";
import { fmtDuration, fmtNumber, humanize, isEmptyObject } from "@/lib/format";
import type { AgentName, JSONObject } from "@/lib/types";

// Defensive accessors: agent outputs are untyped JSON from the backend.
const str = (v: unknown): string => (typeof v === "string" ? v : v === null || v === undefined ? "" : String(v));
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const strs = (v: unknown): string[] => arr(v).map(str).filter(Boolean);
const obj = (v: unknown): JSONObject => (v && typeof v === "object" && !Array.isArray(v) ? (v as JSONObject) : {});

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">{title}</h4>
      {children}
    </section>
  );
}

function List({ items, ordered }: { items: string[]; ordered?: boolean }) {
  if (!items.length) return <p className="text-sm text-zinc-500">—</p>;
  const Tag = ordered ? "ol" : "ul";
  return (
    <Tag className={`${ordered ? "list-decimal" : "list-disc"} space-y-1 pl-5 text-sm text-zinc-300`}>
      {items.map((t, i) => (
        <li key={i}>{t}</li>
      ))}
    </Tag>
  );
}

function Para({ children }: { children: ReactNode }) {
  return <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-300">{children || "—"}</p>;
}

function Confidence({ value }: { value: number | null }) {
  if (value === null) return <span className="text-zinc-500">—</span>;
  const pct = Math.round(value * 100);
  return <Badge tone={pct >= 75 ? "green" : pct >= 50 ? "amber" : "red"}>{pct}%</Badge>;
}

function Research({ d }: { d: JSONObject }) {
  const facts = arr(d.key_facts).map(obj);
  return (
    <div className="space-y-6">
      <Section title="Summary">
        <Para>{str(d.summary)}</Para>
      </Section>
      <Section title="Key facts">
        {facts.length ? (
          <Table>
            <thead>
              <tr>
                <th>Fact</th>
                <th>Source</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {facts.map((f, i) => (
                <tr key={i}>
                  <td className="min-w-[240px]">{str(f.fact)}</td>
                  <td className="text-zinc-500">{str(f.source_hint)}</td>
                  <td>
                    <Confidence value={num(f.confidence)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <p className="text-sm text-zinc-500">—</p>
        )}
      </Section>
      <div className="grid gap-6 md:grid-cols-2">
        <Section title="Content angles">
          <List items={strs(d.content_angles)} />
        </Section>
        <Section title="Audience insights">
          <List items={strs(d.audience_insights)} />
        </Section>
        <Section title="Open questions">
          <List items={strs(d.open_questions)} />
        </Section>
        <Section title="Keywords">
          <Chips items={strs(d.keywords)} />
        </Section>
      </div>
    </div>
  );
}

function Strategy({ d }: { d: JSONObject }) {
  return (
    <div className="space-y-6">
      <KeyValue
        items={[
          ["Chosen angle", str(d.chosen_angle) || "—"],
          ["Target emotion", str(d.target_emotion) || "—"],
          ["Estimated duration", fmtDuration(num(d.estimated_duration_sec))],
          ["Call to action", str(d.call_to_action) || "—"],
        ]}
      />
      <Section title="Rationale">
        <Para>{str(d.rationale)}</Para>
      </Section>
      <div className="grid gap-6 md:grid-cols-3">
        <Section title="Hook options">
          <List items={strs(d.hook_options)} />
        </Section>
        <Section title="Structure">
          <List items={strs(d.structure)} ordered />
        </Section>
        <Section title="Title ideas">
          <List items={strs(d.title_ideas)} />
        </Section>
      </div>
    </div>
  );
}

function Script({ d }: { d: JSONObject }) {
  const sections = arr(d.sections).map(obj);
  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-zinc-50">{str(d.title) || "Untitled script"}</h3>
        <p className="mt-1 text-xs text-zinc-500">
          {fmtNumber(num(d.word_count))} words · ~{fmtDuration(num(d.estimated_duration_sec))}
        </p>
      </div>
      <Section title="Hook">
        <blockquote className="border-l-2 border-accent-500 pl-4 text-sm italic text-zinc-200">{str(d.hook) || "—"}</blockquote>
      </Section>
      <Section title="Sections">
        <ol className="space-y-4">
          {sections.map((s, i) => (
            <li key={i} className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-4">
              <p className="text-sm font-medium text-zinc-100">
                <span className="mr-2 text-zinc-500">{i + 1}.</span>
                {str(s.heading)}
              </p>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-zinc-300">{str(s.narration)}</p>
              {str(s.visual_notes) && <p className="mt-2 text-xs text-zinc-500">Visuals: {str(s.visual_notes)}</p>}
            </li>
          ))}
        </ol>
      </Section>
      <Section title="Call to action">
        <Para>{str(d.call_to_action)}</Para>
      </Section>
      {str(d.full_narration) && (
        <details className="rounded-lg border border-zinc-800 p-4">
          <summary className="cursor-pointer text-sm font-medium text-zinc-300">Full narration</summary>
          <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-zinc-400">{str(d.full_narration)}</p>
        </details>
      )}
    </div>
  );
}

function FactCheck({ d }: { d: JSONObject }) {
  const claims = arr(d.claims).map(obj);
  const verdict = str(d.verdict);
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Badge tone={verdict === "pass" ? "green" : "amber"}>Verdict: {verdict || "—"}</Badge>
        <span className="text-sm text-zinc-400">
          Overall confidence <Confidence value={num(d.overall_confidence)} />
        </span>
      </div>
      <Section title="Claims">
        {claims.length ? (
          <Table>
            <thead>
              <tr>
                <th>Claim</th>
                <th>Status</th>
                <th>Note</th>
                <th>Suggested fix</th>
              </tr>
            </thead>
            <tbody>
              {claims.map((c, i) => {
                const st = str(c.status);
                return (
                  <tr key={i}>
                    <td className="min-w-[220px]">{str(c.claim)}</td>
                    <td>
                      <Badge tone={st === "supported" ? "green" : st === "unverified" ? "amber" : "red"}>{humanize(st)}</Badge>
                    </td>
                    <td className="text-zinc-400">{str(c.note) || "—"}</td>
                    <td className="text-zinc-400">{str(c.suggested_fix) || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        ) : (
          <p className="text-sm text-zinc-500">No claims recorded.</p>
        )}
      </Section>
      <Section title="Required changes">
        <List items={strs(d.required_changes)} />
      </Section>
    </div>
  );
}

function Storyboard({ d }: { d: JSONObject }) {
  const scenes = arr(d.scenes).map(obj);
  return (
    <div className="space-y-6">
      <KeyValue
        items={[
          ["Visual style", str(d.visual_style) || "—"],
          ["Music mood", str(d.music_mood) || "—"],
          ["Total duration", fmtDuration(num(d.total_duration_sec))],
          ["Scenes", String(scenes.length)],
        ]}
      />
      <Table>
        <thead>
          <tr>
            <th>#</th>
            <th>Duration</th>
            <th>Narration</th>
            <th>Visual prompt</th>
            <th>Shot / motion</th>
            <th>Transition</th>
            <th>Overlay</th>
          </tr>
        </thead>
        <tbody>
          {scenes.map((s, i) => (
            <tr key={i}>
              <td className="tabular-nums text-zinc-500">{num(s.index) ?? i}</td>
              <td className="tabular-nums">{num(s.duration_sec)?.toFixed(1) ?? "—"}s</td>
              <td className="min-w-[220px]">{str(s.narration)}</td>
              <td className="min-w-[200px] text-zinc-400">{str(s.visual_prompt)}</td>
              <td className="whitespace-nowrap text-zinc-400">
                {str(s.shot_type) || "—"} · {humanize(str(s.motion))}
              </td>
              <td className="text-zinc-400">{str(s.transition) || "—"}</td>
              <td className="text-zinc-400">{str(s.overlay_text) || "—"}</td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  );
}

function Optimization({ d }: { d: JSONObject }) {
  const notes = obj(d.platform_notes);
  const seo = num(d.seo_score);
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        {seo !== null && <Badge tone={seo >= 75 ? "green" : seo >= 50 ? "amber" : "red"}>SEO score {seo}/100</Badge>}
        {str(d.thumbnail_text) && <Badge tone="accent">Thumbnail: “{str(d.thumbnail_text)}”</Badge>}
      </div>
      <div className="grid gap-6 md:grid-cols-2">
        <Section title="Title options">
          <List items={strs(d.titles)} ordered />
        </Section>
        <Section title="Best posting times (UTC)">
          <Chips items={strs(d.best_posting_times_utc)} />
        </Section>
      </div>
      <Section title="Description">
        <Para>{str(d.description)}</Para>
      </Section>
      <div className="grid gap-6 md:grid-cols-2">
        <Section title="Tags">
          <Chips items={strs(d.tags)} />
        </Section>
        <Section title="Hashtags">
          <Chips items={strs(d.hashtags)} tone="accent" />
        </Section>
      </div>
      <Section title="Thumbnail prompt">
        <Para>{str(d.thumbnail_prompt)}</Para>
      </Section>
      <div className="grid gap-6 md:grid-cols-2">
        <Section title="YouTube notes">
          <Para>{str(notes.youtube)}</Para>
        </Section>
        <Section title="Instagram notes">
          <Para>{str(notes.instagram)}</Para>
        </Section>
      </div>
    </div>
  );
}

const RENDERERS: Record<AgentName, (p: { d: JSONObject }) => ReactElement> = {
  research: Research,
  strategy: Strategy,
  script: Script,
  fact_check: FactCheck,
  storyboard: Storyboard,
  optimization: Optimization,
};

export function AgentOutput({ agent, data }: { agent: AgentName; data: JSONObject | undefined }) {
  if (isEmptyObject(data)) {
    return <EmptyState title={`No ${humanize(agent).toLowerCase()} output yet`} description="Run the AI agents to generate this section." />;
  }
  const R = RENDERERS[agent];
  return (
    <div className="prose-output">
      <R d={data as JSONObject} />
    </div>
  );
}

export function StepStatus({ status }: { status: string }) {
  return <StatusBadge status={status} />;
}
