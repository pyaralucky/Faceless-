"use client";

import { useMemo, useRef, useState } from "react";
import { fmtCompact, fmtNumber } from "@/lib/format";

export interface Point {
  x: string; // ISO date (YYYY-MM-DD)
  y: number;
}

/**
 * Single-series line chart in inline SVG: 2px line, recessive grid, one y-axis,
 * crosshair + tooltip on hover/touch/keyboard. The title outside names the series.
 */
export function LineChart({ points, height = 240, label = "Value" }: { points: Point[]; height?: number; label?: string }) {
  const width = 800;
  const pad = { top: 16, right: 16, bottom: 28, left: 48 };
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const { path, area, xs, ys, ticks } = useMemo(() => {
    const maxY = Math.max(1, ...points.map((p) => p.y));
    const niceMax = niceCeil(maxY);
    const iw = width - pad.left - pad.right;
    const ih = height - pad.top - pad.bottom;
    const xs = points.map((_, i) => pad.left + (points.length <= 1 ? iw / 2 : (i / (points.length - 1)) * iw));
    const ys = points.map((p) => pad.top + ih - (p.y / niceMax) * ih);
    const path = xs.map((x, i) => `${i ? "L" : "M"}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(" ");
    const base = pad.top + ih;
    const area = xs.length ? `${path} L${xs[xs.length - 1].toFixed(1)},${base} L${xs[0].toFixed(1)},${base} Z` : "";
    const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => ({ v: niceMax * f, y: pad.top + ih - f * ih }));
    return { path, area, xs, ys, ticks };
  }, [points, height, pad.left, pad.right, pad.top, pad.bottom]);

  if (!points.length) return <div className="flex h-40 items-center justify-center text-sm text-zinc-500">No data in this period.</div>;

  const onMove = (clientX: number) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const x = ((clientX - rect.left) / rect.width) * width;
    let best = 0;
    for (let i = 1; i < xs.length; i++) if (Math.abs(xs[i] - x) < Math.abs(xs[best] - x)) best = i;
    setHover(best);
  };

  const labelEvery = Math.max(1, Math.ceil(points.length / 7));
  const h = hover !== null ? points[hover] : null;

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto w-full touch-none select-none"
        role="img"
        aria-label={`${label} over time, ${points.length} days, latest ${fmtNumber(points[points.length - 1].y)}`}
        tabIndex={0}
        onMouseMove={(e) => onMove(e.clientX)}
        onTouchMove={(e) => e.touches[0] && onMove(e.touches[0].clientX)}
        onMouseLeave={() => setHover(null)}
        onBlur={() => setHover(null)}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") setHover((v) => Math.min(points.length - 1, (v ?? -1) + 1));
          if (e.key === "ArrowLeft") setHover((v) => Math.max(0, (v ?? points.length) - 1));
        }}
      >
        <defs>
          <linearGradient id="lc-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#818cf8" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#818cf8" stopOpacity="0" />
          </linearGradient>
        </defs>
        {ticks.map((t) => (
          <g key={t.v}>
            <line x1={pad.left} x2={width - pad.right} y1={t.y} y2={t.y} stroke="#27272a" strokeWidth={1} />
            <text x={pad.left - 8} y={t.y + 4} textAnchor="end" className="fill-zinc-500" fontSize={11}>
              {fmtCompact(t.v)}
            </text>
          </g>
        ))}
        {points.map((p, i) =>
          i % labelEvery === 0 || i === points.length - 1 ? (
            <text key={p.x} x={xs[i]} y={height - 8} textAnchor="middle" className="fill-zinc-500" fontSize={11}>
              {shortDate(p.x)}
            </text>
          ) : null,
        )}
        <path d={area} fill="url(#lc-fill)" />
        <path d={path} fill="none" stroke="#818cf8" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {hover !== null && (
          <g>
            <line x1={xs[hover]} x2={xs[hover]} y1={pad.top} y2={height - pad.bottom} stroke="#52525b" strokeWidth={1} strokeDasharray="3 3" />
            <circle cx={xs[hover]} cy={ys[hover]} r={5} fill="#818cf8" stroke="#09090b" strokeWidth={2} />
          </g>
        )}
        {/* wide invisible hit area */}
        <rect x={pad.left} y={pad.top} width={width - pad.left - pad.right} height={height - pad.top - pad.bottom} fill="transparent" />
      </svg>
      {h && hover !== null && (
        <div
          className="pointer-events-none absolute top-2 rounded-md border border-zinc-700 bg-zinc-900/95 px-3 py-2 text-xs shadow-lg"
          style={{ left: `${(xs[hover] / width) * 100}%`, transform: `translateX(${xs[hover] > width * 0.7 ? "-105%" : "8px"})` }}
        >
          <p className="text-zinc-400">{shortDate(h.x, true)}</p>
          <p className="font-semibold tabular-nums text-zinc-100">
            {fmtNumber(h.y)} <span className="font-normal text-zinc-400">{label.toLowerCase()}</span>
          </p>
        </div>
      )}
    </div>
  );
}

function niceCeil(v: number): number {
  const exp = Math.pow(10, Math.floor(Math.log10(v)));
  const f = v / exp;
  const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return nice * exp;
}

function shortDate(iso: string, long = false): string {
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, long ? { weekday: "short", month: "short", day: "numeric", year: "numeric" } : { month: "short", day: "numeric" });
}
