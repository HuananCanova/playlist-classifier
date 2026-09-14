import React, { useMemo, useState } from "react";
import ChartTooltip from "./ChartTooltip.jsx";
import {
  INK_MUTED,
  NEUTRAL,
  SERIES,
  SURFACE,
  gaussianSmooth,
  pct,
  smoothPath,
  useMounted,
  useWidth,
} from "./chartKit.js";

const MAX_SERIES = 5; // + "outros" = seis cores, o teto validado da paleta
const OTHER = "outros";
const PAD_X = 8;
const MIN_TRACKS = 6;

/** Cor de texto que passa contraste dentro de um preenchimento colorido. */
function inkOn(hex) {
  const n = parseInt(hex.slice(1), 16);
  const lin = (c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const L = 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
  return L > 0.2 ? "#0a0a0a" : "#ffffff";
}

/**
 * Parcela de cada gênero em cada posição da playlist.
 *
 * Cada faixa vale uma unidade, dividida igualmente entre os gêneros principais
 * que ela tem — assim uma faixa com três tags não pesa três vezes mais que uma
 * com uma. Só vai para "outros" a faixa que não tem nenhum gênero principal:
 * uma faixa de techno com uma tag rara a mais continua sendo techno, e dar
 * uma fatia a "outros" por isso inflava o cinza até dominar o desenho.
 * Faixas sem gênero valem zero, e o vão aparece como um estreitamento.
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

export default function GenreFlow({ tracks, genreDistribution, trackCount }) {
  const [wrapRef, width] = useWidth();
  const mounted = useMounted();
  const [hoverIndex, setHoverIndex] = useState(null);
  const [focusSeries, setFocusSeries] = useState(null);
  const [pointer, setPointer] = useState(null);

  const series = useMemo(() => buildFlow(tracks, genreDistribution), [tracks, genreDistribution]);
  const n = tracks.length;
  const height = width < 560 ? 190 : 250;
  const plotW = Math.max(width - PAD_X * 2, 1);
  const xAt = (i) => PAD_X + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);

  // Empilhamento centrado (silhueta): o total em cada ponto é a fração da faixa
  // que tem gênero, então a fita afina onde há faixas sem tag.
  const layout = useMemo(() => {
    if (!width || n < MIN_TRACKS || !series.length) return null;
    const bands = series.map(() => ({ top: [], bottom: [] }));
    for (let i = 0; i < n; i++) {
      const total = series.reduce((sum, s) => sum + s.values[i], 0);
      let y = ((1 - Math.min(total, 1)) / 2) * height;
      series.forEach((s, k) => {
        const h = s.values[i] * height;
        bands[k].top.push([xAt(i), y]);
        bands[k].bottom.push([xAt(i), y + h]);
        y += h;
      });
    }
    return bands.map((b, k) => {
      const path =
        smoothPath(b.top) + smoothPath(b.bottom.slice().reverse(), { move: false }) + "Z";
      // Rótulo direto no ponto mais grosso da fita, se couber.
      let best = 0;
      let bestH = -1;
      b.top.forEach(([, yTop], i) => {
        const h = b.bottom[i][1] - yTop;
        if (h > bestH) {
          bestH = h;
          best = i;
        }
      });
      const labelW = series[k].label.length * 6.6 + 16;
      const lx = Math.min(Math.max(xAt(best), PAD_X + labelW / 2), width - PAD_X - labelW / 2);
      return {
        path,
        // Em tela estreita os rótulos se atropelam; ali a legenda basta.
        label:
          width >= 560 && bestH >= 22 && labelW < plotW / 3
            ? { x: lx, y: b.top[best][1] + bestH / 2 }
            : null,
        bands: b,
      };
    });
  }, [series, width, height, n]);

  if (n < MIN_TRACKS || !series.length) return null;

  const active = focusSeries;
  const hovered = hoverIndex != null ? tracks[hoverIndex] : null;

  function indexFromEvent(e) {
    const r = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - r.left;
    const i = Math.round(((x - PAD_X) / plotW) * (n - 1));
    return { i: Math.max(0, Math.min(n - 1, i)), x, y: e.clientY - r.top };
  }

  function onMove(e) {
    const { i, x, y } = indexFromEvent(e);
    setHoverIndex(i);
    setPointer({ x, y });
    // Qual fita está sob o cursor, nesta posição.
    const k = layout?.findIndex((l) => y >= l.bands.top[i][1] && y <= l.bands.bottom[i][1]);
    setFocusSeries(k != null && k >= 0 ? k : null);
  }

  function onKey(e) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft" && e.key !== "Home" && e.key !== "End") return;
    e.preventDefault();
    const cur = hoverIndex ?? -1;
    const next =
      e.key === "Home" ? 0 : e.key === "End" ? n - 1 : cur + (e.key === "ArrowRight" ? 1 : -1);
    const i = Math.max(0, Math.min(n - 1, next));
    setHoverIndex(i);
    setPointer({ x: xAt(i), y: height * 0.3 });
  }

  const mix =
    hoverIndex != null
      ? series
          .map((s) => ({ ...s, v: s.values[hoverIndex] }))
          .filter((s) => s.v > 0.02)
          .sort((a, b) => b.v - a.v)
          .slice(0, 4)
      : [];

  const quarters = [0, 1, 2, 3].map((q) => {
    const from = Math.floor((q * n) / 4);
    const to = Math.max(from + 1, Math.floor(((q + 1) * n) / 4));
    return { from, to };
  });

  return (
    <section className="panel panel-flow">
      <header className="panel-head">
        <h3>O caminho dos gêneros</h3>
        <p className="panel-sub">
          Da primeira à última faixa, na ordem da playlist. A espessura de cada fita é a
          parcela daquele gênero naquele trecho; onde a fita afina, há faixas sem gênero.
        </p>
      </header>

      <ul className="viz-legend" aria-label="Gêneros no gráfico">
        {series.map((s, k) => (
          <li key={s.label}>
            <button
              type="button"
              className={`viz-legend-item${active != null && active !== k ? " is-dim" : ""}`}
              onMouseEnter={() => setFocusSeries(k)}
              onMouseLeave={() => setFocusSeries(null)}
              onFocus={() => setFocusSeries(k)}
              onBlur={() => setFocusSeries(null)}
            >
              <span className="viz-swatch" style={{ background: s.color }} aria-hidden="true" />
              {s.label}
              {s.total != null && <span className="viz-legend-value">{pct(s.total, trackCount)}</span>}
            </button>
          </li>
        ))}
      </ul>

      <div className="flow-wrap" ref={wrapRef}>
        {layout && (
          <>
            <svg
              className={`flow-plot${mounted ? " is-in" : ""}`}
              width={width}
              height={height + 34}
              role="img"
              aria-label={`Fluxo dos gêneros ao longo das ${n} faixas da playlist. Use as setas para percorrer as faixas.`}
              tabIndex={0}
              onMouseMove={onMove}
              onMouseLeave={() => {
                setHoverIndex(null);
                setFocusSeries(null);
              }}
              onKeyDown={onKey}
              onBlur={() => setHoverIndex(null)}
            >
              <defs>
                <clipPath id="flow-round">
                  <rect x={PAD_X} y={0} width={plotW} height={height} rx={14} />
                </clipPath>
              </defs>

              <g clipPath="url(#flow-round)">
              <g className="flow-layers">
                {layout.map((l, k) => (
                  <path
                    key={series[k].label}
                    d={l.path}
                    fill={series[k].color}
                    stroke={SURFACE}
                    strokeWidth={2}
                    strokeLinejoin="round"
                    className={`flow-layer${active != null && active !== k ? " is-dim" : ""}`}
                  />
                ))}
              </g>
              </g>

              {layout.map((l, k) =>
                l.label ? (
                  <text
                    key={`label-${series[k].label}`}
                    x={l.label.x}
                    y={l.label.y}
                    className={`flow-label${active != null && active !== k ? " is-dim" : ""}`}
                    fill={inkOn(series[k].color)}
                    textAnchor="middle"
                    dominantBaseline="central"
                  >
                    {series[k].label}
                  </text>
                ) : null,
              )}

              {/* Uma marca por faixa: cheia se tem gênero, vazada se não tem. */}
              <g transform={`translate(0, ${height + 10})`}>
                {tracks.map((t, i) => (
                  <rect
                    key={t.track_id}
                    x={xAt(i) - 1}
                    y={0}
                    width={2}
                    height={t.genres.length ? 8 : 4}
                    rx={1}
                    fill={t.genres.length ? INK_MUTED : "rgba(167,167,167,0.35)"}
                    opacity={hoverIndex === i ? 1 : 0.55}
                  />
                ))}
              </g>
              <g className="viz-axis" transform={`translate(0, ${height + 31})`}>
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

              {hoverIndex != null && (
                <line
                  x1={xAt(hoverIndex)}
                  x2={xAt(hoverIndex)}
                  y1={0}
                  y2={height + 18}
                  className="viz-crosshair"
                />
              )}
            </svg>

            <ChartTooltip
              visible={hovered != null && pointer != null}
              x={pointer?.x ?? 0}
              y={Math.min(pointer?.y ?? 0, height - 40)}
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
                        <li key={s.label}>
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
