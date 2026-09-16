import React, { useMemo, useState } from "react";
import ChartTooltip from "./ChartTooltip.jsx";
import { NEUTRAL, SERIES, niceMax, useMounted, useWidth } from "./chartKit.js";

const HEIGHT = 260;
const PAD_TOP = 26;
const AXIS_H = 26;
const GAP = 5; // vão entre colunas de anos vizinhos
const SEG_GAP = 2; // vão da cor do painel entre gêneros empilhados
const RADIUS = 4;
const OTHER = "outros";

/** Retângulo com o topo arredondado; a base fica reta, presa no segmento de baixo. */
function capPath(x, y, w, h) {
  const r = Math.min(RADIUS, w / 2, h);
  if (h <= 0) return "";
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

/**
 * O gosto ano a ano: uma coluna por ano, empilhada pelos gêneros que você mais
 * escolhe. A altura diz quanta música entrou naquele ano; a divisão da coluna
 * diz de quê ela era feita — é a mudança do gosto que o gráfico mostra, não o
 * volume.
 *
 * Empilhadas, e não em 100%: um ano com seis faixas teria a mesma barra cheia
 * de um ano com seiscentas, e a proporção de uma amostra minúscula pareceria
 * tão firme quanto a de uma grande. Com contagem, o ano magro se anuncia.
 *
 * O gênero dominante fica na base — é a partir dele que se lê a pilha. O
 * backend já reparte cada faixa entre os gêneros que ela tem, então a soma da
 * coluna continua sendo "faixas escolhidas naquele ano".
 *
 * `genres`: rótulos na ordem das séries. `years`: [{ year, tracks, counts }],
 * com `counts` na mesma ordem e uma posição final para "outros".
 */
export default function TasteTimeline({ genres, years }) {
  const [wrapRef, width] = useWidth();
  const mounted = useMounted();
  const [hover, setHover] = useState(null);
  const [focus, setFocus] = useState(null);

  const series = useMemo(
    () =>
      [...genres.map((label, i) => ({ label, color: SERIES[i] })), { label: OTHER, color: NEUTRAL }].map((s, i) => ({
        ...s,
        i,
        total: years.reduce((sum, y) => sum + (y.counts[i] ?? 0), 0),
      })),
    [genres, years],
  );

  // Uma série sem nenhuma faixa (ex.: "outros" quando tudo é do topo) não
  // ganha lugar na legenda: seria uma cor a decorar sem nada para apontar.
  const shown = useMemo(() => series.filter((s) => s.total > 0), [series]);

  const model = useMemo(() => {
    if (!width || years.length === 0) return null;
    const max = niceMax(Math.max(...years.map((y) => y.tracks), 1));
    const plotH = HEIGHT - PAD_TOP - AXIS_H;
    const step = width / years.length;
    const colW = Math.max(step - GAP, 1);
    const baseline = PAD_TOP + plotH;

    const cols = years.map((y, i) => {
      const x = i * step + GAP / 2;
      const parts = [];
      let acc = 0;
      // De baixo para cima, na ordem das séries: o gênero dominante na base.
      series.forEach((s) => {
        const v = y.counts[s.i] ?? 0;
        if (v <= 0) return;
        const h = (v / max) * plotH;
        parts.push({ ...s, value: v, top: baseline - acc - h, h });
        acc += h;
      });
      parts.forEach((p, k) => {
        p.isCap = k === parts.length - 1;
        // O vão só existe onde sobra altura para ele. Num gênero de dois pixels,
        // abrir dois de vão apagaria o segmento e o ano pareceria ter um furo.
        p.gap = p.h > SEG_GAP * 2.5 ? SEG_GAP : 0;
      });
      return { ...y, i, x, w: colW, parts, height: acc, top: baseline - acc };
    });

    // Um rótulo a cada `every` anos, para nenhum encostar no vizinho.
    const every = Math.max(1, Math.ceil(38 / step));
    const ticks = cols.filter((c) => c.i % every === 0);

    let peak = 0;
    cols.forEach((c, i) => {
      if (c.tracks > cols[peak].tracks) peak = i;
    });

    return { max, plotH, baseline, step, cols, ticks, peak };
  }, [series, years, width]);

  if (years.length === 0) {
    return <p className="muted panel-empty">Sem datas de quando as faixas entraram.</p>;
  }

  function onMove(e) {
    if (!model) return;
    const r = e.currentTarget.getBoundingClientRect();
    const i = Math.min(years.length - 1, Math.max(0, Math.floor((e.clientX - r.left) / model.step)));
    setHover(model.cols[i]);
  }

  const first = years[0].year;
  const last = years[years.length - 1].year;

  return (
    <>
      <ul className="viz-legend" onMouseLeave={() => setFocus(null)}>
        {shown.map((s) => (
          <li key={s.label}>
            <button
              type="button"
              className={`viz-legend-item${focus != null && focus !== s.i ? " is-dim" : ""}`}
              onMouseEnter={() => setFocus(s.i)}
              onFocus={() => setFocus(s.i)}
              onBlur={() => setFocus(null)}
              onClick={() => setFocus((f) => (f === s.i ? null : s.i))}
              aria-pressed={focus === s.i}
            >
              <span className="viz-swatch" style={{ background: s.color }} aria-hidden="true" />
              {s.label}
              <span className="viz-legend-value">{Math.round(s.total).toLocaleString("pt-BR")}</span>
            </button>
          </li>
        ))}
      </ul>

      <div className="colchart-wrap" ref={wrapRef}>
        {model && (
          <>
            <svg
              width={width}
              height={HEIGHT}
              role="img"
              aria-label={`Faixas que entraram nas suas playlists a cada ano, de ${first} a ${last}, divididas entre ${shown
                .map((s) => s.label)
                .join(", ")}`}
              className="colchart"
              onMouseMove={onMove}
              onMouseLeave={() => setHover(null)}
            >
              {[0.5, 1].map((f) => (
                <g key={f} className="viz-axis">
                  <line
                    x1={0}
                    x2={width}
                    y1={PAD_TOP + model.plotH * (1 - f)}
                    y2={PAD_TOP + model.plotH * (1 - f)}
                    className="colchart-grid"
                  />
                  <text x={0} y={PAD_TOP + model.plotH * (1 - f) - 5}>
                    {Math.round(model.max * f).toLocaleString("pt-BR")}
                  </text>
                </g>
              ))}

              {model.cols.map((c) => (
                <g
                  key={c.year}
                  className="taste-col"
                  style={{
                    opacity: hover && hover.i !== c.i ? 0.5 : 1,
                    transform: mounted ? "scaleY(1)" : "scaleY(0)",
                    transformOrigin: `0 ${model.baseline}px`,
                    transitionDelay: `${Math.min(c.i, 30) * 24}ms`,
                  }}
                >
                  {c.parts.map((p) => (
                    <path
                      key={p.label}
                      // O vão vai no topo de cada segmento: a cor do painel separa
                      // os gêneros sem contorno, e a base fica colada no de baixo.
                      d={p.isCap ? capPath(c.x, p.top, c.w, p.h) : `M${c.x},${p.top + p.gap}h${c.w}v${p.h - p.gap}h${-c.w}Z`}
                      fill={p.color}
                      style={{ opacity: focus != null && focus !== p.i ? 0.22 : 1 }}
                    />
                  ))}
                </g>
              ))}

              <line x1={0} x2={width} y1={model.baseline} y2={model.baseline} className="viz-baseline" />

              {/* Rótulo direto só no ano de pico: o resto fica no hover. */}
              {model.cols[model.peak].tracks > 0 && !hover && (
                <text
                  x={Math.min(Math.max(model.cols[model.peak].x + model.cols[model.peak].w / 2, 16), width - 16)}
                  y={model.cols[model.peak].top - 7}
                  textAnchor="middle"
                  className="colchart-peak"
                >
                  {model.cols[model.peak].tracks.toLocaleString("pt-BR")}
                </text>
              )}

              <g className="viz-axis" transform={`translate(0, ${HEIGHT - 6})`}>
                {model.ticks.map((t) => (
                  <text key={t.year} x={t.x + t.w / 2} textAnchor="middle">
                    {t.year}
                  </text>
                ))}
              </g>
            </svg>

            <ChartTooltip
              visible={hover != null}
              x={hover ? hover.x + hover.w / 2 : 0}
              y={hover ? Math.max(hover.top, PAD_TOP + 24) : 0}
              width={width}
            >
              {hover && (
                <>
                  <span className="viz-tooltip-kicker">{hover.year}</span>
                  <span className="viz-tooltip-title">
                    {hover.tracks.toLocaleString("pt-BR")} {hover.tracks === 1 ? "faixa" : "faixas"}
                  </span>
                  {hover.parts.length > 0 ? (
                    <ul className="viz-tooltip-list">
                      {[...hover.parts].reverse().map((p) => (
                        <li key={p.label}>
                          <span className="viz-swatch" style={{ background: p.color }} aria-hidden="true" />
                          <span>{p.label}</span>
                          <span className="viz-tooltip-num">{Math.round((p.value / hover.tracks) * 100)}%</span>
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
