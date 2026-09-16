import React, { useId, useMemo, useState } from "react";
import ChartTooltip from "./ChartTooltip.jsx";
import {
  INK_MUTED,
  NEUTRAL,
  SERIES,
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

// Três atos: o suficiente para dizer "começa assim, muda no meio, termina
// assado" sem picotar uma playlist de 30 faixas em pedaços de cinco.
const ACTS = [
  { key: "abertura", label: "abertura" },
  { key: "meio", label: "meio" },
  { key: "fecho", label: "fecho" },
];

const LANE_H = 26;

// Luz vinda de cima, como no relevo da capa. Cada fita é sombreada na própria
// espessura — clara na aresta de cima, escura na de baixo —, e a separação entre
// duas vizinhas é esse contraste, não um contorno desenhado. Traço escuro em
// volta de área chapada é desenho animado; o que separa volumes é a luz.
const TOPO = "rgba(255, 255, 255, 0.5)";
const SOMBRA = "rgba(0, 0, 0, 0.5)";

/** Mistura a cor com branco (t > 0) ou preto (t < 0). */
function shade(hex, t) {
  const n = parseInt(hex.slice(1), 16);
  const alvo = t > 0 ? 255 : 0;
  const k = Math.abs(t);
  const canal = (c) => Math.round(c + (alvo - c) * k);
  const r = canal((n >> 16) & 255);
  const g = canal((n >> 8) & 255);
  const b = canal(n & 255);
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, "0")}`;
}


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

/**
 * Os três atos da playlist, cada um com o gênero que mais aparece nele.
 *
 * Usa o `raw`, não o suavizado: a suavização existe para o desenho não tremer,
 * mas a contagem de um trecho tem que ser a contagem real daquele trecho.
 */
export function buildActs(series, n) {
  return ACTS.map((act, a) => {
    const from = Math.floor((a * n) / 3);
    const to = a === 2 ? n : Math.floor(((a + 1) * n) / 3);
    const span = Math.max(to - from, 1);

    const scored = series
      .map((s, k) => ({
        k,
        label: s.label,
        color: s.color,
        share: s.raw.slice(from, to).reduce((sum, v) => sum + v, 0) / span,
      }))
      .sort((x, y) => y.share - x.share);

    // "outros" nunca é o rótulo de um ato: dizer que o trecho é "outros" não
    // descreve nada. Se ele domina, o ato fica sem gênero declarado.
    const top = scored.find((s) => s.label !== OTHER && s.share > 0.08) ?? null;
    return { ...act, from, to, top, dominant: scored[0] ?? null };
  });
}

/** Uma frase que descreve o arco da playlist a partir dos três atos. */
export function describeArc(acts) {
  const [a, b, c] = acts.map((act) => act.top?.label ?? null);

  if (!a && !b && !c) return "Não há gênero identificado o bastante para descrever um caminho.";
  if (a && a === b && b === c) return `Fica em ${a} do começo ao fim, sem mudar de território.`;
  if (a && c && a === c && b && b !== a) return `Abre em ${a}, passa por ${b} no meio e volta para ${a}.`;
  if (a && b && a === b && c && c !== a) return `Sustenta ${a} na maior parte e fecha virando para ${c}.`;
  if (b && c && b === c && a && a !== b) return `Abre em ${a} e assenta em ${b} até o fim.`;
  if (a && b && c) return `Abre em ${a}, passa por ${b} e fecha em ${c}.`;

  const named = acts.filter((act) => act.top);
  if (named.length === 1) return `O trecho de ${named[0].label} é o único com gênero claro: ${named[0].top.label}.`;
  return named.map((act) => `${act.label} em ${act.top.label}`).join(", ") + ".";
}

export default function GenreFlow({ tracks, genreDistribution, trackCount }) {
  const [wrapRef, width] = useWidth();
  const uid = useId().replace(/:/g, "");
  const mounted = useMounted();
  const [hoverIndex, setHoverIndex] = useState(null);
  const [focusSeries, setFocusSeries] = useState(null);
  const [pointer, setPointer] = useState(null);

  const series = useMemo(() => buildFlow(tracks, genreDistribution), [tracks, genreDistribution]);
  const n = tracks.length;
  const height = width < 560 ? 190 : 250;
  const plotW = Math.max(width - PAD_X * 2, 1);
  const xAt = (i) => PAD_X + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);

  const acts = useMemo(
    () => (series.length && n >= MIN_TRACKS ? buildActs(series, n) : []),
    [series, n],
  );
  const arc = useMemo(() => (acts.length ? describeArc(acts) : ""), [acts]);

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
        // As arestas viram traço próprio: a de cima recebe o brilho, a de
        // baixo a sombra que encosta na fita seguinte.
        topo: smoothPath(b.top),
        base: smoothPath(b.bottom),
        // Em tela estreita os rótulos se atropelam; ali a legenda basta.
        label:
          width >= 560 && bestH >= 22 && labelW < plotW / 3
            ? { x: lx, y: b.top[best][1] + bestH / 2 }
            : null,
        bands: b,
      };
    });
  }, [series, width, height, n]);

  // Cada gênero numa faixa própria, com a altura relativa ao próprio pico: a
  // fita empilhada mostra a mistura, e estas mostram onde cada um se concentra
  // — inclusive os pequenos, que na fita viram um fio fino demais para ler.
  const lanes = useMemo(() => {
    if (!width || !series.length) return [];
    const laneW = Math.max(width - PAD_X * 2, 1);
    const lx = (i) => PAD_X + (n <= 1 ? laneW / 2 : (i / (n - 1)) * laneW);
    return series.map((s) => {
      const peak = Math.max(...s.values, 0.0001);
      const pts = s.values.map((v, i) => [lx(i), LANE_H - (v / peak) * (LANE_H - 3)]);
      return {
        label: s.label,
        color: s.color,
        total: s.total,
        area: `${smoothPath(pts)}L${lx(n - 1)},${LANE_H}L${lx(0)},${LANE_H}Z`,
        line: smoothPath(pts),
      };
    });
  }, [series, width, n]);

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

  // Em qual ato está a faixa sob o cursor — o ato correspondente acende junto.
  const hoverAct = hoverIndex == null ? -1 : acts.findIndex((a) => hoverIndex >= a.from && hoverIndex < a.to);

  return (
    <section className="panel panel-flow">
      <header className="panel-head">
        <div className="panel-head-row">
          <h3>O caminho dos gêneros</h3>
          <span className="flow-scale">{n} faixas, na ordem da playlist</span>
        </div>
        <p className="flow-arc">{arc}</p>
        <p className="panel-sub">
          A espessura de cada fita é a parcela daquele gênero naquele trecho; onde a fita
          afina, há faixas sem gênero.
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
                {/* A fita se dissolve nas pontas em vez de bater numa borda,
                    como o relevo da tela de entrada. Uma playlist não começa
                    nem termina na parede de um retângulo. */}
                {/* 8% de cada lado: o relevo da capa usa 12%, mas ele é só
                    enfeite. Aqui a fita carrega dado, e a dissolução não pode
                    apagar as primeiras e as últimas faixas — o cursor e o
                    balão continuam exatos por cima dela. */}
                <linearGradient id={`fade-${uid}`} x1="0" x2="1" y1="0" y2="0">
                  <stop offset="0" stopColor="#000" />
                  <stop offset="0.08" stopColor="#fff" />
                  <stop offset="0.92" stopColor="#fff" />
                  <stop offset="1" stopColor="#000" />
                </linearGradient>
                {/* `userSpaceOnUse` explícito: por padrão a área da máscara é
                    relativa à caixa do que ela recobre, e a fita muda de caixa
                    a cada ponto do desenho — o resultado era a fita cortada no
                    meio. Aqui a área é a mesma do gráfico, em coordenadas. */}
                {/* Um gradiente por fita, na caixa da própria fita: como a
                    espessura varia ao longo da playlist, o sombreado acompanha
                    e o volume se mantém onde ela afina. */}
                {series.map((serie, k) => (
                  <linearGradient
                    key={serie.label}
                    id={`vol-${uid}-${k}`}
                    x1="0"
                    x2="0"
                    y1="0"
                    y2="1"
                  >
                    <stop offset="0" stopColor={shade(serie.color, 0.42)} />
                    <stop offset="0.14" stopColor={shade(serie.color, 0.16)} />
                    <stop offset="0.46" stopColor={serie.color} />
                    <stop offset="1" stopColor={shade(serie.color, -0.46)} />
                  </linearGradient>
                ))}
                <mask
                  id={`flow-mask-${uid}`}
                  maskUnits="userSpaceOnUse"
                  x={0}
                  y={0}
                  width={width}
                  height={height}
                >
                  <rect
                    x={0}
                    y={0}
                    width={width}
                    height={height}
                    fill={`url(#fade-${uid})`}
                  />
                </mask>
              </defs>

              <g mask={`url(#flow-mask-${uid})`}>
              <g className="flow-layers">
                {layout.map((l, k) => (
                  <g
                    key={series[k].label}
                    className={`flow-layer${active != null && active !== k ? " is-dim" : ""}`}
                  >
                    <path d={l.path} fill={`url(#vol-${uid}-${k})`} />
                    <path d={l.base} fill="none" stroke={SOMBRA} strokeWidth={1.5} />
                    <path d={l.topo} fill="none" stroke={TOPO} strokeWidth={1} />
                  </g>
                ))}
              </g>

              {/* Divisas dos atos, por dentro do recorte: marcam onde o ato
                  muda sem desenhar por cima das bordas arredondadas. */}
              {acts.slice(1).map((a) => (
                <line
                  key={a.key}
                  className="flow-act-divider"
                  x1={xAt(a.from)}
                  x2={xAt(a.from)}
                  y1={0}
                  y2={height}
                />
              ))}
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
                    {hoverAct >= 0 && ` — ${acts[hoverAct].label}`}
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

      <ol className="flow-acts" aria-label="Os três trechos da playlist">
        {acts.map((a, i) => (
          <li
            key={a.key}
            className={`flow-act${hoverAct === i ? " is-hover" : ""}`}
            style={a.top ? { "--act-color": a.top.color } : undefined}
          >
            <span className="flow-act-name">{a.label}</span>
            <span className="flow-act-genre">
              {a.top ? (
                <>
                  <span className="viz-swatch" style={{ background: a.top.color }} aria-hidden="true" />
                  {a.top.label}
                </>
              ) : (
                <span className="muted">sem gênero dominante</span>
              )}
            </span>
            <span className="flow-act-range tabular">
              faixas {a.from + 1}–{a.to}
              {a.top && <span className="flow-act-share"> · {Math.round(a.top.share * 100)}%</span>}
            </span>
          </li>
        ))}
      </ol>

      <div className="flow-lanes">
        <p className="flow-lanes-head">
          Onde cada gênero se concentra. A altura é relativa ao pico do próprio gênero, então
          um gênero pequeno também aparece — o tamanho real está no número ao lado.
        </p>
        <ul>
          {lanes.map((lane, k) => (
            <li
              key={lane.label}
              className={`flow-lane${active != null && active !== k ? " is-dim" : ""}`}
              onMouseEnter={() => setFocusSeries(k)}
              onMouseLeave={() => setFocusSeries(null)}
            >
              <span className="flow-lane-label" title={lane.label}>
                <span className="viz-swatch" style={{ background: lane.color }} aria-hidden="true" />
                {lane.label}
              </span>
              {/* A faixa é desenhada na escala do painel e reescalada para a
                  célula, que é mais estreita por causa do rótulo. Sem o
                  `viewBox` o desenho passava da célula e era cortado à direita;
                  `non-scaling-stroke` impede que o achatamento afine o traço. */}
              <span className="flow-lane-plot">
                <svg
                  viewBox={`0 0 ${width} ${LANE_H}`}
                  preserveAspectRatio="none"
                  width="100%"
                  height={LANE_H}
                  aria-hidden="true"
                >
                  <path d={lane.area} fill={lane.color} opacity={0.28} />
                  <path
                    d={lane.line}
                    fill="none"
                    stroke={lane.color}
                    strokeWidth={1.5}
                    vectorEffect="non-scaling-stroke"
                  />
                  {hoverIndex != null && (
                    <line
                      className="viz-crosshair"
                      vectorEffect="non-scaling-stroke"
                      x1={xAt(hoverIndex)}
                      x2={xAt(hoverIndex)}
                      y1={0}
                      y2={LANE_H}
                    />
                  )}
                </svg>
              </span>
              <span className="flow-lane-value tabular">
                {lane.total ?? "—"}
                {lane.total != null && (
                  <span className="flow-lane-share">{pct(lane.total, trackCount)}</span>
                )}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {/* A mesma leitura em tabela, para leitor de tela: parcela média por quarto da playlist. */}
      {/* Tabela não respeita a largura de 1px do sr-only; quem esconde é o div. */}
      <div className="sr-only">
      <p>{arc}</p>
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
