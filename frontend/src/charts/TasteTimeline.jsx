import React, { useId, useMemo, useState } from "react";
import ChartTooltip from "./ChartTooltip.jsx";
import { NEUTRAL, SERIES, niceMax, placeCallouts, smoothPath, useMounted, useWidth } from "./chartKit.js";

const PAD_X = 8;
const INSET = 34; // folga nas pontas para o primeiro e o último ano não colarem na borda
const PAD_TOP = 26;
const AXIS_H = 34;
const HOVER_RADIUS = 26;
const OTHER = "outros";

/**
 * O gosto ano a ano, na mesma linguagem do caminho dos gêneros: uma linha por
 * gênero que você mais escolhe, com a coluna do total do ano ao fundo.
 *
 * A coluna mantém o que a pilha antiga dizia de graça — quanta música entrou
 * naquele ano —, e as linhas mostram a mudança do gosto, que é o assunto do
 * gráfico. Contagem e não porcentagem: um ano com seis faixas teria o mesmo
 * peso visual de um ano com seiscentas, e a proporção de uma amostra minúscula
 * pareceria tão firme quanto a de uma grande. Com contagem, o ano magro se
 * anuncia.
 *
 * O backend já reparte cada faixa entre os gêneros que ela tem, então as
 * linhas de um ano somam o total da coluna.
 *
 * `genres`: rótulos na ordem das séries. `years`: [{ year, tracks, counts }],
 * com `counts` na mesma ordem e uma posição final para "outros".
 */
export default function TasteTimeline({ genres, years }) {
  const [wrapRef, width] = useWidth();
  const mounted = useMounted();
  const uid = useId().replace(/:/g, "");
  const [hover, setHover] = useState(null); // índice do ano sob o cursor
  const [pointerY, setPointerY] = useState(null);
  // Duas fontes para o mesmo destaque, e a distinção importa: o mouse por cima
  // destaca enquanto estiver lá, o clique prende. Com um estado só, o
  // `mouseenter` do próprio clique já deixava a série destacada, o clique via
  // que ela era a atual e desprendia — no mouse, clicar na legenda nunca
  // prendia nada.
  const [pinned, setPinned] = useState(null);
  const [hoveredSeries, setHoveredSeries] = useState(null);
  const focus = pinned ?? hoveredSeries;

  const series = useMemo(
    () =>
      [...genres.map((label, i) => ({ label, color: SERIES[i] })), { label: OTHER, color: NEUTRAL }].map((s, i) => ({
        ...s,
        i,
        values: years.map((y) => y.counts[i] ?? 0),
        total: years.reduce((sum, y) => sum + (y.counts[i] ?? 0), 0),
      })),
    [genres, years],
  );

  // Uma série sem nenhuma faixa (ex.: "outros" quando tudo é do topo) não
  // ganha lugar na legenda nem linha: seria uma cor a decorar sem nada para apontar.
  const shown = useMemo(() => series.filter((s) => s.total > 0), [series]);

  const compact = width < 560;
  const plotH = compact ? 180 : 240;
  const baseline = PAD_TOP + plotH;
  const n = years.length;

  const model = useMemo(() => {
    if (!width || n === 0 || shown.length === 0) return null;
    const left = PAD_X + INSET;
    const right = width - PAD_X - INSET;
    const xAt = (i) => (n === 1 ? (left + right) / 2 : left + (i / (n - 1)) * (right - left));
    const max = niceMax(Math.max(...years.map((y) => y.tracks), 1));
    const yAt = (v) => baseline - (v / max) * plotH;
    const step = n === 1 ? right - left : (right - left) / (n - 1);
    const colW = Math.min(46, Math.max(10, step * 0.42));

    const cols = years.map((y, i) => ({ ...y, i, x: xAt(i), top: yAt(y.tracks) }));
    const lines = shown.map((s) => {
      const pts = s.values.map((v, i) => [xAt(i), yAt(v)]);
      const line = smoothPath(pts);
      return { pts, line, area: `${line}L${xAt(n - 1)},${baseline}L${xAt(0)},${baseline}Z` };
    });

    const grid = [0.25, 0.5, 0.75, 1].map((f) => ({ y: yAt(max * f), value: Math.round(max * f) }));

    // Um rótulo de ano a cada `every`, para nenhum encostar no vizinho.
    const every = Math.max(1, Math.ceil(40 / step));

    let peak = 0;
    cols.forEach((c, i) => {
      if (c.tracks > cols[peak].tracks) peak = i;
    });

    // Os números da grade ocupam o canto esquerdo: rótulo nenhum pode cair ali.
    const reserved = grid.map((g) => ({ x0: PAD_X, x1: PAD_X + 30, y0: g.y - 16, y1: g.y - 2 }));
    const callouts = compact
      ? []
      : placeCallouts(shown, lines, { left: PAD_X + 4, right: width - PAD_X - 4, top: 2, bottom: baseline - 4, reserved });

    return { xAt, colW, cols, lines, grid, every, peak, callouts, left, right, step };
  }, [shown, years, width, n, plotH, baseline, compact]);

  if (n === 0) {
    return <p className="muted panel-empty">Sem datas de quando as faixas entraram.</p>;
  }

  const dim = (k) => focus != null && focus !== shown[k].i;
  const state = (k) => `${dim(k) ? " is-dim" : ""}${focus === shown[k].i ? " is-focus" : ""}`;
  // O gênero em foco é desenhado por último, por cima dos outros.
  const order = shown.map((_, k) => k).sort((a, b) => (shown[a].i === focus) - (shown[b].i === focus));

  function onMove(e) {
    if (!model) return;
    const r = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;
    const i = n === 1 ? 0 : Math.max(0, Math.min(n - 1, Math.round((x - model.left) / model.step)));
    setHover(i);
    setPointerY(y);

    let best = null;
    let bestD = HOVER_RADIUS;
    model.lines.forEach((l, k) => {
      if (shown[k].values[i] <= 0) return;
      const d = Math.abs(l.pts[i][1] - y);
      if (d < bestD) {
        bestD = d;
        best = shown[k].i;
      }
    });
    setHoveredSeries(best);
  }

  function onLeave() {
    setHover(null);
    setPointerY(null);
    setHoveredSeries(null);
  }

  function onKey(e) {
    if (e.key === "Escape") {
      setPinned(null);
      return;
    }
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft" && e.key !== "Home" && e.key !== "End") return;
    e.preventDefault();
    const cur = hover ?? -1;
    const next = e.key === "Home" ? 0 : e.key === "End" ? n - 1 : cur + (e.key === "ArrowRight" ? 1 : -1);
    setHover(Math.max(0, Math.min(n - 1, next)));
    setPointerY(PAD_TOP + plotH * 0.3);
  }

  const first = years[0].year;
  const last = years[n - 1].year;
  const hovered = hover != null ? years[hover] : null;
  const mix =
    hovered != null
      ? shown
          .map((s) => ({ ...s, v: s.values[hover] }))
          .filter((s) => s.v > 0)
          .sort((a, b) => b.v - a.v)
      : [];
  const svgH = baseline + AXIS_H;

  return (
    <>
      <ul className="viz-legend" onMouseLeave={() => setHoveredSeries(null)}>
        {shown.map((s) => (
          <li key={s.label}>
            <button
              type="button"
              className={`viz-legend-item${focus != null && focus !== s.i ? " is-dim" : ""}${pinned === s.i ? " is-pinned" : ""}`}
              onMouseEnter={() => setHoveredSeries(s.i)}
              onFocus={() => setHoveredSeries(s.i)}
              onBlur={() => setHoveredSeries(null)}
              onClick={() => setPinned((p) => (p === s.i ? null : s.i))}
              aria-pressed={pinned === s.i}
              title={pinned === s.i ? "Clique para soltar" : `Isolar ${s.label}`}
            >
              <span className="viz-swatch viz-swatch-dot" style={{ background: s.color, color: s.color }} aria-hidden="true" />
              {s.label}
              <span className="viz-legend-value">{Math.round(s.total).toLocaleString("pt-BR")}</span>
            </button>
          </li>
        ))}
      </ul>

      <div className="flow-wrap" ref={wrapRef}>
        {model && (
          <>
            <svg
              width={width}
              height={svgH}
              role="img"
              aria-label={`Faixas que entraram nas suas playlists a cada ano, de ${first} a ${last}, com uma linha para cada gênero: ${shown
                .map((s) => s.label)
                .join(", ")}. Use as setas para percorrer os anos.`}
              className={`flow-plot taste-plot${mounted ? " is-in" : ""}`}
              tabIndex={0}
              onPointerMove={onMove}
              onPointerLeave={onLeave}
              onKeyDown={onKey}
              onBlur={() => setHover(null)}
            >
              <defs>
                {shown.map((s, k) => (
                  <linearGradient key={s.label} id={`${uid}-fill-${k}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" stopColor={s.color} stopOpacity={0.38} />
                    <stop offset="0.7" stopColor={s.color} stopOpacity={0.06} />
                    <stop offset="1" stopColor={s.color} stopOpacity={0} />
                  </linearGradient>
                ))}
                <linearGradient id={`${uid}-col`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor="#ffffff" stopOpacity={0.09} />
                  <stop offset="1" stopColor="#ffffff" stopOpacity={0.02} />
                </linearGradient>
                {/* Em espaço do usuário: numa linha reta a caixa do traço tem altura zero, e o filtro sumiria com ela. */}
                <filter id={`${uid}-glow`} filterUnits="userSpaceOnUse" x={0} y={0} width={width} height={svgH}>
                  <feGaussianBlur stdDeviation="5" />
                </filter>
                <clipPath id={`${uid}-plot`}>
                  <rect x={PAD_X} y={PAD_TOP - 14} width={width - PAD_X * 2} height={plotH + 14} rx={12} />
                </clipPath>
              </defs>

              <rect className="flow-bg" x={PAD_X} y={PAD_TOP - 14} width={width - PAD_X * 2} height={plotH + 14} rx={12} />
              <g className="flow-grid" aria-hidden="true">
                {model.grid.map((g) => (
                  <g key={g.value}>
                    <line x1={PAD_X} x2={width - PAD_X} y1={g.y} y2={g.y} />
                    <text x={PAD_X + 8} y={g.y - 5} className="taste-grid-value">
                      {g.value.toLocaleString("pt-BR")}
                    </text>
                  </g>
                ))}
              </g>

              {/* O total do ano, ao fundo: quanta música entrou. */}
              <g className="taste-cols" aria-hidden="true">
                {model.cols.map((c) => {
                  const h = baseline - c.top;
                  if (h <= 0) return null;
                  const r = Math.min(8, model.colW / 2, h);
                  const x = c.x - model.colW / 2;
                  return (
                    <path
                      key={c.year}
                      d={`M${x},${baseline}V${c.top + r}Q${x},${c.top} ${x + r},${c.top}H${x + model.colW - r}Q${x + model.colW},${c.top} ${x + model.colW},${c.top + r}V${baseline}Z`}
                      fill={`url(#${uid}-col)`}
                      className={`taste-col${hover === c.i ? " is-hover" : ""}`}
                      style={{ transitionDelay: mounted ? `${Math.min(c.i, 30) * 40}ms, 0ms` : "0ms" }}
                    />
                  );
                })}
              </g>

              <g className="flow-areas" clipPath={`url(#${uid}-plot)`}>
                {order.map((k) => (
                  <path key={shown[k].label} d={model.lines[k].area} fill={`url(#${uid}-fill-${k})`} className={`flow-area${state(k)}`} />
                ))}
              </g>

              <g className="flow-glows" filter={`url(#${uid}-glow)`} aria-hidden="true">
                {order.map((k) => (
                  <path
                    key={shown[k].label}
                    d={model.lines[k].line}
                    stroke={shown[k].color}
                    pathLength={1}
                    className={`flow-glow${state(k)}`}
                  />
                ))}
              </g>

              <g className="flow-lines">
                {order.map((k) => (
                  <path
                    key={shown[k].label}
                    d={model.lines[k].line}
                    stroke={shown[k].color}
                    pathLength={1}
                    className={`flow-line${state(k)}`}
                  />
                ))}
              </g>

              {/* Os anos do gênero em foco viram pontos: a curva sozinha esconde onde está o dado.
                  Só dele — em todas as linhas ao mesmo tempo, os pontos embolam perto do chão. */}
              <g className="taste-points" aria-hidden="true">
                {order.map((k) =>
                  focus === shown[k].i
                    ? model.lines[k].pts.map(([x, y], i) =>
                        shown[k].values[i] > 0 ? (
                          <circle key={`${shown[k].label}-${i}`} cx={x} cy={y} r={3} fill={shown[k].color} className="taste-point" />
                        ) : null,
                      )
                    : null,
                )}
              </g>

              <g className="flow-callouts" aria-hidden="true">
                {model.callouts.map((c) => (
                  <g key={shown[c.k].label} className={`flow-callout${state(c.k)}`}>
                    <line x1={c.sx} y1={c.sy} x2={c.ex} y2={c.ey} stroke={shown[c.k].color} className="flow-leader" />
                    <circle cx={c.x} cy={c.y} r={4} fill={shown[c.k].color} className="flow-callout-dot" />
                    <text x={c.lx} y={c.ly} textAnchor="middle" dominantBaseline="central" className="flow-callout-text">
                      {shown[c.k].label}
                    </text>
                  </g>
                ))}
              </g>

              {/* Total só no ano de pico; o resto fica no hover. */}
              {hover == null && model.cols[model.peak].tracks > 0 && (
                <text
                  x={model.cols[model.peak].x}
                  y={model.cols[model.peak].top - 8}
                  textAnchor="middle"
                  className="taste-total"
                >
                  {model.cols[model.peak].tracks.toLocaleString("pt-BR")}
                </text>
              )}

              {hover != null && (
                <g className="flow-hover" aria-hidden="true">
                  <line
                    x1={model.cols[hover].x}
                    x2={model.cols[hover].x}
                    y1={PAD_TOP - 14}
                    y2={baseline + 6}
                    className="flow-hover-line"
                  />
                  {model.cols[hover].tracks > 0 && (
                    <text x={model.cols[hover].x} y={model.cols[hover].top - 8} textAnchor="middle" className="taste-total">
                      {model.cols[hover].tracks.toLocaleString("pt-BR")}
                    </text>
                  )}
                  {order.map((k) => {
                    if (shown[k].values[hover] <= 0 || dim(k)) return null;
                    const [x, y] = model.lines[k].pts[hover];
                    const isFocus = focus === shown[k].i;
                    return (
                      <g key={shown[k].label}>
                        {isFocus && <circle cx={x} cy={y} r={11} fill={shown[k].color} className="flow-hover-halo" />}
                        <circle cx={x} cy={y} r={isFocus ? 5.5 : 4} fill={shown[k].color} className="flow-hover-dot" />
                      </g>
                    );
                  })}
                </g>
              )}

              <g className="viz-axis" transform={`translate(0, ${baseline + 24})`}>
                {model.cols
                  .filter((c) => c.i % model.every === 0 || c.i === hover)
                  .map((c) => (
                    <text key={c.year} x={c.x} textAnchor="middle" className={c.i === hover ? "is-hover" : undefined}>
                      {c.year}
                    </text>
                  ))}
              </g>
            </svg>

            <ChartTooltip
              visible={hovered != null}
              x={hover != null ? model.cols[hover].x : 0}
              y={Math.max(40, Math.min(pointerY ?? 0, baseline - 40))}
              width={width}
            >
              {hovered && (
                <>
                  <span className="viz-tooltip-kicker">{hovered.year}</span>
                  <span className="viz-tooltip-title">
                    {hovered.tracks.toLocaleString("pt-BR")} {hovered.tracks === 1 ? "faixa entrou" : "faixas entraram"}
                  </span>
                  {mix.length > 0 ? (
                    <ul className="viz-tooltip-list">
                      {mix.map((s) => (
                        <li key={s.label} className={focus === s.i ? "is-focus" : undefined}>
                          <span className="viz-swatch" style={{ background: s.color }} aria-hidden="true" />
                          <span>{s.label}</span>
                          <span className="viz-tooltip-num">{Math.round((s.v / hovered.tracks) * 100)}%</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <span className="viz-tooltip-sub">Nenhuma faixa entrou neste ano.</span>
                  )}
                </>
              )}
            </ChartTooltip>
          </>
        )}
      </div>
    </>
  );
}
