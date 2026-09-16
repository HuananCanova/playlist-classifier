import React, { useId, useMemo, useState } from "react";
import ChartTooltip from "./ChartTooltip.jsx";
import {
  INK_MUTED,
  NEUTRAL,
  SERIES,
  gaussianSmooth,
  pct,
  placeCallouts,
  smoothPath,
  useMounted,
  useWidth,
} from "./chartKit.js";

const MAX_SERIES = 5; // + "outros" = seis cores, o teto validado da paleta
const OTHER = "outros";
const PAD_X = 8;
const PAD_TOP = 26;
const AXIS_H = 40;
const MIN_TRACKS = 6;
const HOVER_RADIUS = 26; // distância, em px, até onde o cursor "pega" uma linha

/**
 * Parcela de cada gênero em cada posição da playlist.
 *
 * Cada faixa vale uma unidade, dividida igualmente entre os gêneros principais
 * que ela tem — assim uma faixa com três tags não pesa três vezes mais que uma
 * com uma. Só vai para "outros" a faixa que não tem nenhum gênero principal:
 * uma faixa de techno com uma tag rara a mais continua sendo techno, e dar
 * uma fatia a "outros" por isso inflava o cinza até dominar o desenho.
 * Faixas sem gênero valem zero para todas as linhas.
 */
export function buildFlow(tracks, genreDistribution) {
  const top = genreDistribution.slice(0, MAX_SERIES).map((g) => g.label);
  const topSet = new Set(top);

  const raw = top.map(() => new Array(tracks.length).fill(0));
  const other = new Array(tracks.length).fill(0);
  let hasOther = false;

  tracks.forEach((t, i) => {
    const matched = t.genres.filter((g) => topSet.has(g));
    if (matched.length) {
      matched.forEach((g) => {
        raw[top.indexOf(g)][i] = 1 / matched.length;
      });
    } else if (t.genres.length) {
      other[i] = 1;
      hasOther = true;
    }
  });

  const series = top.map((label, s) => ({ label, color: SERIES[s], raw: raw[s] }));
  if (hasOther) series.push({ label: OTHER, color: NEUTRAL, raw: other });

  // Janela proporcional ao tamanho: numa playlist de 300 faixas, 1 faixa de
  // largura vira ruído; numa de 12, uma janela larga apagaria tudo.
  const sigma = Math.min(8, Math.max(1, tracks.length / 16));
  series.forEach((s) => {
    s.values = gaussianSmooth(s.raw, sigma);
    s.total = genreDistribution.find((g) => g.label === s.label)?.count ?? null;
  });

  return series;
}

/** Teto do eixo em quartos: a linha mais alta usa a altura, sem colar no topo. */
function yCeiling(peak) {
  return Math.min(1, Math.max(0.25, Math.ceil(peak * 1.12 * 4) / 4));
}

export default function GenreFlow({ tracks, genreDistribution, trackCount }) {
  const [wrapRef, width] = useWidth();
  const mounted = useMounted();
  const uid = useId().replace(/:/g, "");
  const [hoverIndex, setHoverIndex] = useState(null);
  const [pointer, setPointer] = useState(null);
  // Como no gosto ano a ano: passar o mouse destaca enquanto estiver lá, o
  // clique na legenda prende até o próximo clique.
  const [hoveredSeries, setHoveredSeries] = useState(null);
  const [pinned, setPinned] = useState(null);
  const focus = pinned ?? hoveredSeries;

  const series = useMemo(() => buildFlow(tracks, genreDistribution), [tracks, genreDistribution]);
  const n = tracks.length;
  const compact = width < 560;
  const plotH = compact ? 190 : 260;
  const baseline = PAD_TOP + plotH;
  const plotW = Math.max(width - PAD_X * 2, 1);
  const xAt = (i) => PAD_X + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);

  const model = useMemo(() => {
    if (!width || n < MIN_TRACKS || !series.length) return null;
    let peak = 0.01;
    series.forEach((s) => s.values.forEach((v) => (peak = Math.max(peak, v))));
    const ceil = yCeiling(peak);
    const yAt = (v) => baseline - (v / ceil) * plotH;

    const lines = series.map((s) => {
      const pts = s.values.map((v, i) => [xAt(i), yAt(v)]);
      const line = smoothPath(pts);
      return { pts, line, area: `${line}L${xAt(n - 1)},${baseline}L${xAt(0)},${baseline}Z` };
    });

    const gridY = [0.25, 0.5, 0.75, 1].map((f) => yAt(ceil * f));
    const columns = Math.min(n - 1, compact ? 6 : 12);
    const gridX = Array.from({ length: columns - 1 }, (_, c) => PAD_X + ((c + 1) / columns) * plotW);

    // Em tela estreita os rótulos se atropelam; ali a legenda basta.
    const callouts = compact
      ? []
      : placeCallouts(series, lines, { left: PAD_X + 4, right: PAD_X + plotW - 4, top: 2, bottom: baseline - 4 });

    return { lines, gridY, gridX, callouts };
    // xAt depende só de width e n, que já estão na lista.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, width, n, plotH, baseline, compact]);

  if (n < MIN_TRACKS || !series.length) return null;

  const hovered = hoverIndex != null ? tracks[hoverIndex] : null;
  const dim = (k) => focus != null && focus !== k;
  const state = (k) => `${dim(k) ? " is-dim" : ""}${focus === k ? " is-focus" : ""}`;
  // O gênero em foco é desenhado por último, por cima dos outros.
  const order = series.map((_, k) => k).sort((a, b) => (a === focus) - (b === focus));

  function onMove(e) {
    if (!model) return;
    const r = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;
    const i = Math.max(0, Math.min(n - 1, Math.round(((x - PAD_X) / plotW) * (n - 1))));
    setHoverIndex(i);
    setPointer({ x, y });

    // A linha mais perto do cursor nesta faixa ganha o destaque.
    let best = null;
    let bestD = HOVER_RADIUS;
    model.lines.forEach((l, k) => {
      if (series[k].values[i] < 0.01) return;
      const d = Math.abs(l.pts[i][1] - y);
      if (d < bestD) {
        bestD = d;
        best = k;
      }
    });
    setHoveredSeries(best);
  }

  function onLeave() {
    setHoverIndex(null);
    setPointer(null);
    setHoveredSeries(null);
  }

  function onKey(e) {
    if (e.key === "Escape") {
      setPinned(null);
      return;
    }
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft" && e.key !== "Home" && e.key !== "End") return;
    e.preventDefault();
    const cur = hoverIndex ?? -1;
    const next =
      e.key === "Home" ? 0 : e.key === "End" ? n - 1 : cur + (e.key === "ArrowRight" ? 1 : -1);
    const i = Math.max(0, Math.min(n - 1, next));
    setHoverIndex(i);
    setPointer({ x: xAt(i), y: PAD_TOP + plotH * 0.3 });
  }

  const mix =
    hoverIndex != null
      ? series
          .map((s, k) => ({ ...s, k, v: s.values[hoverIndex] }))
          .filter((s) => s.v > 0.02)
          .sort((a, b) => b.v - a.v)
      : [];

  const quarters = [0, 1, 2, 3].map((q) => {
    const from = Math.floor((q * n) / 4);
    const to = Math.max(from + 1, Math.floor(((q + 1) * n) / 4));
    return { from, to };
  });

  const svgH = baseline + AXIS_H;

  return (
    <section className="panel panel-flow">
      <header className="panel-head">
        <h3>O caminho dos gêneros</h3>
        <p className="panel-sub">
          Da primeira à última faixa, na ordem da playlist. A altura de cada linha é a parcela daquele gênero naquele
          trecho. Passe o mouse para ver faixa a faixa; clique na legenda para isolar um gênero.
        </p>
      </header>

      <ul className="viz-legend" aria-label="Gêneros no gráfico" onMouseLeave={() => setHoveredSeries(null)}>
        {series.map((s, k) => (
          <li key={s.label}>
            <button
              type="button"
              className={`viz-legend-item${dim(k) ? " is-dim" : ""}${pinned === k ? " is-pinned" : ""}`}
              onMouseEnter={() => setHoveredSeries(k)}
              onFocus={() => setHoveredSeries(k)}
              onBlur={() => setHoveredSeries(null)}
              onClick={() => setPinned((p) => (p === k ? null : k))}
              aria-pressed={pinned === k}
              title={pinned === k ? "Clique para soltar" : `Isolar ${s.label}`}
            >
              <span className="viz-swatch viz-swatch-dot" style={{ background: s.color, color: s.color }} aria-hidden="true" />
              {s.label}
              {s.total != null && <span className="viz-legend-value">{pct(s.total, trackCount)}</span>}
            </button>
          </li>
        ))}
      </ul>

      <div className="flow-wrap" ref={wrapRef}>
        {model && (
          <>
            <svg
              className={`flow-plot${mounted ? " is-in" : ""}${focus != null ? " has-focus" : ""}`}
              width={width}
              height={svgH}
              role="img"
              aria-label={`Parcela de cada gênero ao longo das ${n} faixas da playlist. Use as setas para percorrer as faixas.`}
              tabIndex={0}
              onPointerMove={onMove}
              onPointerLeave={onLeave}
              onKeyDown={onKey}
              onBlur={() => setHoverIndex(null)}
            >
              <defs>
                {series.map((s, k) => (
                  <linearGradient key={s.label} id={`${uid}-fill-${k}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" stopColor={s.color} stopOpacity={0.42} />
                    <stop offset="0.7" stopColor={s.color} stopOpacity={0.07} />
                    <stop offset="1" stopColor={s.color} stopOpacity={0} />
                  </linearGradient>
                ))}
                {/* Em espaço do usuário: numa linha reta a caixa do traço tem altura zero, e o filtro sumiria com ela. */}
                <filter id={`${uid}-glow`} filterUnits="userSpaceOnUse" x={0} y={0} width={width} height={svgH}>
                  <feGaussianBlur stdDeviation="5" />
                </filter>
                <clipPath id={`${uid}-plot`}>
                  <rect x={PAD_X} y={PAD_TOP - 14} width={plotW} height={plotH + 14} rx={12} />
                </clipPath>
              </defs>

              <rect className="flow-bg" x={PAD_X} y={PAD_TOP - 14} width={plotW} height={plotH + 14} rx={12} />
              <g className="flow-grid" aria-hidden="true">
                {model.gridY.map((y) => (
                  <line key={`y${y}`} x1={PAD_X} x2={PAD_X + plotW} y1={y} y2={y} />
                ))}
                {model.gridX.map((x) => (
                  <line key={`x${x}`} x1={x} x2={x} y1={PAD_TOP - 14} y2={baseline} />
                ))}
              </g>

              <g className="flow-areas" clipPath={`url(#${uid}-plot)`}>
                {order.map((k) => (
                  <path
                    key={series[k].label}
                    d={model.lines[k].area}
                    fill={`url(#${uid}-fill-${k})`}
                    className={`flow-area${state(k)}`}
                  />
                ))}
              </g>

              <g className="flow-glows" filter={`url(#${uid}-glow)`} aria-hidden="true">
                {order.map((k) => (
                  <path
                    key={series[k].label}
                    d={model.lines[k].line}
                    stroke={series[k].color}
                    pathLength={1}
                    className={`flow-glow${state(k)}`}
                  />
                ))}
              </g>

              <g className="flow-lines">
                {order.map((k) => (
                  <path
                    key={series[k].label}
                    d={model.lines[k].line}
                    stroke={series[k].color}
                    pathLength={1}
                    className={`flow-line${state(k)}`}
                  />
                ))}
              </g>

              <g className="flow-callouts" aria-hidden="true">
                {model.callouts.map((c) => (
                  <g key={series[c.k].label} className={`flow-callout${state(c.k)}`}>
                    <line x1={c.sx} y1={c.sy} x2={c.ex} y2={c.ey} stroke={series[c.k].color} className="flow-leader" />
                    <circle cx={c.x} cy={c.y} r={4} fill={series[c.k].color} className="flow-callout-dot" />
                    <text x={c.lx} y={c.ly} textAnchor="middle" dominantBaseline="central" className="flow-callout-text">
                      {series[c.k].label}
                    </text>
                  </g>
                ))}
              </g>

              {hoverIndex != null && (
                <g className="flow-hover" aria-hidden="true">
                  <line
                    x1={xAt(hoverIndex)}
                    x2={xAt(hoverIndex)}
                    y1={PAD_TOP - 14}
                    y2={baseline + 16}
                    className="flow-hover-line"
                  />
                  {order.map((k) => {
                    if (series[k].values[hoverIndex] < 0.01 || dim(k)) return null;
                    const [x, y] = model.lines[k].pts[hoverIndex];
                    return (
                      <g key={series[k].label}>
                        {focus === k && <circle cx={x} cy={y} r={11} fill={series[k].color} className="flow-hover-halo" />}
                        <circle
                          cx={x}
                          cy={y}
                          r={focus === k ? 5.5 : 4}
                          fill={series[k].color}
                          className="flow-hover-dot"
                        />
                      </g>
                    );
                  })}
                </g>
              )}

              {/* Uma marca por faixa: alta se tem gênero, baixa e apagada se não tem. */}
              <g transform={`translate(0, ${baseline + 8})`} aria-hidden="true">
                {tracks.map((t, i) => (
                  <rect
                    key={t.track_id}
                    x={xAt(i) - 0.75}
                    y={0}
                    width={1.5}
                    height={t.genres.length ? 8 : 4}
                    rx={0.75}
                    fill={t.genres.length ? INK_MUTED : "rgba(167,167,167,0.35)"}
                    opacity={hoverIndex === i ? 1 : 0.45}
                  />
                ))}
              </g>
              <g className="viz-axis" transform={`translate(0, ${baseline + 33})`}>
                <text x={PAD_X} textAnchor="start">
                  faixa 1
                </text>
                <text x={xAt(Math.floor((n - 1) / 2))} textAnchor="middle">
                  meio
                </text>
                <text x={width - PAD_X} textAnchor="end">
                  faixa {n}
                </text>
              </g>
            </svg>

            <ChartTooltip
              visible={hovered != null && pointer != null}
              x={pointer?.x ?? 0}
              y={Math.max(40, Math.min(pointer?.y ?? 0, baseline - 40))}
              width={width}
            >
              {hovered && (
                <>
                  <span className="viz-tooltip-kicker">
                    Faixa {hoverIndex + 1} de {n}
                  </span>
                  <span className="viz-tooltip-title">{hovered.name}</span>
                  <span className="viz-tooltip-sub">{hovered.artists.join(", ")}</span>
                  {mix.length > 0 ? (
                    <ul className="viz-tooltip-list">
                      {mix.map((s) => (
                        <li key={s.label} className={focus === s.k ? "is-focus" : undefined}>
                          <span className="viz-swatch" style={{ background: s.color }} aria-hidden="true" />
                          <span>{s.label}</span>
                          <span className="viz-tooltip-num">{Math.round(s.v * 100)}%</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <span className="viz-tooltip-sub">Trecho sem gênero identificado</span>
                  )}
                </>
              )}
            </ChartTooltip>
          </>
        )}
      </div>

      {/* A mesma leitura em tabela, para leitor de tela: parcela média por quarto da playlist. */}
      {/* Tabela não respeita a largura de 1px do sr-only; quem esconde é o div. */}
      <div className="sr-only">
      <table>
        <caption>Parcela de cada gênero em cada quarto da playlist</caption>
        <thead>
          <tr>
            <th scope="col">Gênero</th>
            {quarters.map((q, i) => (
              <th key={i} scope="col">
                Faixas {q.from + 1} a {q.to}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {series.map((s) => (
            <tr key={s.label}>
              <th scope="row">{s.label}</th>
              {quarters.map((q, i) => {
                const slice = s.raw.slice(q.from, q.to);
                const avg = slice.reduce((a, b) => a + b, 0) / slice.length;
                return <td key={i}>{Math.round(avg * 100)}%</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </section>
  );
}

export const FLOW_SERIES_LIMIT = MAX_SERIES;
