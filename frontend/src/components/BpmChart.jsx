import React, { useMemo, useState } from "react";
import ChartTooltip from "../charts/ChartTooltip.jsx";
import { SERIES, SURFACE, plural, smoothPath, useMounted, useWidth } from "../charts/chartKit.js";

const CURVE_H = 120;
const DOT_R = 4;
const ROW_GAP = 10;
const PAD_X = 14;
const BANDWIDTH = 6; // BPM — largo o bastante para não virar serrilhado com 20 faixas

// Faixas de andamento com nome de gente, não de conservatório.
const ZONES = [
  { from: 0, to: 90, name: "lento" },
  { from: 90, to: 115, name: "moderado" },
  { from: 115, to: 135, name: "dançante" },
  { from: 135, to: 160, name: "acelerado" },
  { from: 160, to: 999, name: "frenético" },
];

/**
 * Andamento faixa a faixa: cada ponto é uma música na sua posição exata de BPM,
 * e a curva por cima é a densidade — onde a playlist se concentra. O
 * histograma de antes jogava fora a posição dentro de cada balde de 20 BPM.
 */
export default function BpmChart({ tracks, averageBpm, missing }) {
  const [wrapRef, width] = useWidth();
  const mounted = useMounted();
  const [hover, setHover] = useState(null);

  const withBpm = useMemo(
    () => tracks.filter((t) => t.bpm != null).sort((a, b) => a.bpm - b.bpm),
    [tracks],
  );

  const model = useMemo(() => {
    if (!width || withBpm.length === 0) return null;
    const bpms = withBpm.map((t) => t.bpm);
    const lo = Math.min(70, Math.floor(bpms[0] / 10) * 10);
    const hi = Math.max(180, Math.ceil(bpms[bpms.length - 1] / 10) * 10);
    const x = (bpm) => PAD_X + ((bpm - lo) / (hi - lo)) * (width - PAD_X * 2);

    // Densidade por kernel gaussiano, amostrada a cada 2 BPM.
    const samples = [];
    for (let b = lo; b <= hi; b += 2) {
      let d = 0;
      for (const v of bpms) d += Math.exp(-((b - v) ** 2) / (2 * BANDWIDTH ** 2));
      samples.push([b, d]);
    }
    const peak = Math.max(...samples.map((s) => s[1]), 1e-9);
    const curve = samples.map(([b, d]) => [x(b), CURVE_H - (d / peak) * (CURVE_H - 18)]);

    // Enxame: cada ponto desce para a primeira fileira onde não encosta em outro.
    const rows = [];
    const dots = withBpm.map((t) => {
      const cx = x(t.bpm);
      let row = 0;
      while (rows[row] != null && cx - rows[row] < DOT_R * 2 + 2) row++;
      rows[row] = cx;
      return { track: t, cx, cy: CURVE_H + 14 + row * ROW_GAP };
    });

    const zones = ZONES.map((z) => ({
      ...z,
      x0: x(Math.max(z.from, lo)),
      x1: x(Math.min(z.to, hi)),
      count: bpms.filter((v) => v >= z.from && v < z.to).length,
    })).filter((z) => z.x1 > z.x0);

    const ticks = [];
    // O último rótulo cede lugar à unidade "BPM" na ponta direita.
    for (let b = Math.ceil(lo / 20) * 20; b <= hi; b += 20) {
      if (x(b) < width - PAD_X - 44) ticks.push({ b, x: x(b) });
    }

    return { lo, hi, x, curve, dots, zones, ticks, height: CURVE_H + 14 + rows.length * ROW_GAP + 34 };
  }, [withBpm, width]);

  if (withBpm.length === 0) {
    return (
      <section className="panel">
        <header className="panel-head">
          <h3>Andamento</h3>
        </header>
        <p className="muted panel-empty">Nenhuma faixa desta playlist tem BPM no catálogo do Deezer.</p>
      </section>
    );
  }

  const dominant = model?.zones.reduce((a, b) => (b.count > a.count ? b : a), model.zones[0]);

  function onMove(e) {
    if (!model) return;
    const r = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - r.left;
    const py = e.clientY - r.top;
    let near = null;
    let best = 14;
    for (const d of model.dots) {
      const dist = Math.hypot(d.cx - px, d.cy - py);
      if (dist < best) {
        best = dist;
        near = d;
      }
    }
    if (near) {
      setHover({ kind: "dot", x: near.cx, y: near.cy, dot: near });
      return;
    }
    const bpm = model.lo + ((px - PAD_X) / (width - PAD_X * 2)) * (model.hi - model.lo);
    const around = withBpm.filter((t) => Math.abs(t.bpm - bpm) <= 5).length;
    setHover({ kind: "x", x: px, y: Math.min(py, CURVE_H - 20), bpm, around });
  }

  const area = model ? `${smoothPath(model.curve)}L${model.curve.at(-1)[0]},${CURVE_H}L${model.curve[0][0]},${CURVE_H}Z` : "";

  return (
    <section className="panel">
      <header className="panel-head">
        <h3>Andamento</h3>
        <p className="panel-sub">
          Cada ponto é uma faixa na sua posição de BPM; a curva mostra onde a playlist se
          concentra.
          {dominant && withBpm.length >= 5 && dominant.count > withBpm.length / 2 && (
            <> A maior parte está na zona {dominant.name}.</>
          )}
        </p>
      </header>

      <div className="bpm-wrap" ref={wrapRef}>
        {model && (
          <>
            <svg
              width={width}
              height={model.height}
              className={`bpm-plot${mounted ? " is-in" : ""}`}
              role="img"
              aria-label={`Distribuição de BPM de ${withBpm.length} faixas${averageBpm != null ? `, média de ${Math.round(averageBpm)} BPM` : ""}.`}
              onMouseMove={onMove}
              onMouseLeave={() => setHover(null)}
            >
              <defs>
                <linearGradient id="bpm-area" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0" stopColor={SERIES[0]} stopOpacity="0.32" />
                  <stop offset="1" stopColor={SERIES[0]} stopOpacity="0.02" />
                </linearGradient>
              </defs>

              {model.zones.map((z, i) => (
                <g key={z.name}>
                  {i % 2 === 1 && (
                    <rect x={z.x0} y={0} width={z.x1 - z.x0} height={model.height - 22} className="bpm-zone" />
                  )}
                  {z.x1 - z.x0 > z.name.length * 6.5 + 8 && (
                    <text x={(z.x0 + z.x1) / 2} y={12} textAnchor="middle" className="bpm-zone-label">
                      {z.name}
                    </text>
                  )}
                </g>
              ))}

              <path d={area} fill="url(#bpm-area)" className="bpm-area" />
              <path d={smoothPath(model.curve)} fill="none" stroke={SERIES[0]} strokeWidth={2} strokeLinecap="round" className="bpm-line" />
              <line x1={PAD_X} x2={width - PAD_X} y1={CURVE_H} y2={CURVE_H} className="viz-baseline" />

              {averageBpm != null && (
                <g className="bpm-avg">
                  <line x1={model.x(averageBpm)} x2={model.x(averageBpm)} y1={22} y2={model.height - 24} />
                  <text
                    x={model.x(averageBpm) + (model.x(averageBpm) > width - 120 ? -6 : 6)}
                    y={40}
                    textAnchor={model.x(averageBpm) > width - 120 ? "end" : "start"}
                  >
                    média {Math.round(averageBpm)}
                  </text>
                </g>
              )}

              {model.dots.map((d, i) => (
                <circle
                  key={d.track.track_id}
                  cx={d.cx}
                  cy={d.cy}
                  r={hover?.dot === d ? DOT_R + 1.5 : DOT_R}
                  fill={SERIES[0]}
                  stroke={SURFACE}
                  strokeWidth={2}
                  className="bpm-dot"
                  style={{ transitionDelay: `${Math.min(i, 60) * 8}ms` }}
                />
              ))}

              <g className="viz-axis" transform={`translate(0, ${model.height - 6})`}>
                {model.ticks.map((t) => (
                  <text key={t.b} x={t.x} textAnchor="middle">
                    {t.b}
                  </text>
                ))}
                <text x={width - PAD_X} textAnchor="end" className="viz-axis-unit">
                  BPM
                </text>
              </g>

              {hover?.kind === "x" && (
                <line x1={hover.x} x2={hover.x} y1={18} y2={CURVE_H} className="viz-crosshair" />
              )}
            </svg>

            <ChartTooltip visible={hover != null} x={hover?.x ?? 0} y={(hover?.y ?? 0) - 8} width={width}>
              {hover?.kind === "dot" && (
                <>
                  <span className="viz-tooltip-kicker">{Math.round(hover.dot.track.bpm)} BPM</span>
                  <span className="viz-tooltip-title">{hover.dot.track.name}</span>
                  <span className="viz-tooltip-sub">{hover.dot.track.artists.join(", ")}</span>
                </>
              )}
              {hover?.kind === "x" && (
                <>
                  <span className="viz-tooltip-kicker">por volta de {Math.round(hover.bpm)} BPM</span>
                  <span className="viz-tooltip-title">
                    {plural(hover.around, "faixa", "faixas")} a até 5 BPM
                  </span>
                </>
              )}
            </ChartTooltip>
          </>
        )}
      </div>

      {missing > 0 && (
        <p className="muted panel-foot">
          {missing} {missing === 1 ? "música sem BPM" : "músicas sem BPM"} no Deezer ficam fora do
          gráfico.
        </p>
      )}
    </section>
  );
}
