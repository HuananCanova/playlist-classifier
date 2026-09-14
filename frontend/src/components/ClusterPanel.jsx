import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import ChartTooltip from "../charts/ChartTooltip.jsx";
import { SERIES, SURFACE, plural, useWidth } from "../charts/chartKit.js";

const HEIGHT = 400;
const PAD = 28;

/*
 * Num gráfico de dispersão qualquer par de grupos pode ficar lado a lado, e a
 * paleta só garante separação para daltônicos entre TODOS os pares nas três
 * primeiras cores. Por isso cada grupo tem também uma forma própria e um
 * rótulo escrito no centro: a cor ajuda, mas nunca é o único jeito de ler.
 */
const SHAPES = ["circle", "square", "triangle", "diamond", "cross", "ring"];

function Marker({ shape, x, y, r, fill }) {
  const common = { fill, stroke: SURFACE, strokeWidth: 2 };
  switch (shape) {
    case "square":
      return <rect x={x - r} y={y - r} width={r * 2} height={r * 2} rx={1.5} {...common} />;
    case "triangle":
      return <path d={`M${x},${y - r * 1.2}L${x + r * 1.15},${y + r * 0.9}L${x - r * 1.15},${y + r * 0.9}Z`} {...common} />;
    case "diamond":
      return <path d={`M${x},${y - r * 1.3}L${x + r * 1.3},${y}L${x},${y + r * 1.3}L${x - r * 1.3},${y}Z`} {...common} />;
    case "cross":
      return (
        <path
          d={`M${x - r},${y - r}L${x + r},${y + r}M${x + r},${y - r}L${x - r},${y + r}`}
          stroke={fill}
          strokeWidth={3}
          strokeLinecap="round"
        />
      );
    case "ring":
      return <circle cx={x} cy={y} r={r} fill={SURFACE} stroke={fill} strokeWidth={2.5} />;
    default:
      return <circle cx={x} cy={y} r={r} {...common} />;
  }
}

export default function ClusterPanel({ playlistId, tracks = [] }) {
  const [dados, setDados] = useState(null);
  const [carregando, setCarregando] = useState(true);
  const [ativo, setAtivo] = useState(null);
  const [hover, setHover] = useState(null);
  const [wrapRef, width] = useWidth();

  useEffect(() => {
    let vivo = true;
    setCarregando(true);
    api
      .getPlaylistClusters(playlistId)
      .then((d) => vivo && setDados(d))
      .catch(() => vivo && setDados(null))
      .finally(() => vivo && setCarregando(false));
    return () => {
      vivo = false;
    };
  }, [playlistId]);

  const nomes = useMemo(() => new Map(tracks.map((t) => [t.track_id, t])), [tracks]);

  const plot = useMemo(() => {
    if (!dados?.points?.length || !width) return null;
    const xs = dados.points.map((p) => p.x);
    const ys = dados.points.map((p) => p.y);
    const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
    const [y0, y1] = [Math.min(...ys), Math.max(...ys)];
    const sx = (v) => PAD + ((v - x0) / (x1 - x0 || 1)) * (width - PAD * 2);
    const sy = (v) => HEIGHT - PAD - ((v - y0) / (y1 - y0 || 1)) * (HEIGHT - PAD * 2);
    const ordem = new Map(dados.clusters.map((c, i) => [c.id, i]));

    const pontos = dados.points.map((p) => ({ ...p, px: sx(p.x), py: sy(p.y), k: ordem.get(p.cluster) ?? 0 }));

    // Halo de cada grupo: centro de massa e espalhamento dos seus pontos.
    const grupos = dados.clusters.map((c, k) => {
      const meus = pontos.filter((p) => p.k === k);
      const cx = meus.reduce((s, p) => s + p.px, 0) / (meus.length || 1);
      const cy = meus.reduce((s, p) => s + p.py, 0) / (meus.length || 1);
      const rx = Math.max(28, Math.sqrt(meus.reduce((s, p) => s + (p.px - cx) ** 2, 0) / (meus.length || 1)) * 2);
      const ry = Math.max(24, Math.sqrt(meus.reduce((s, p) => s + (p.py - cy) ** 2, 0) / (meus.length || 1)) * 2);
      return { ...c, k, cx, cy, rx, ry };
    });

    // Rótulos no alto de cada halo, empurrados para baixo quando encostam em
    // outro já posicionado — grupos sobrepostos tendem a ter o topo no mesmo lugar.
    const colocados = [];
    grupos
      .slice()
      .sort((a, b) => a.cy - a.ry - (b.cy - b.ry))
      .forEach((g) => {
        const w = g.label.length * 6.8 + 8;
        const x = Math.min(Math.max(g.cx, w / 2 + 4), width - w / 2 - 4);
        let y = Math.max(g.cy - g.ry - 6, 14);
        const bate = () =>
          colocados.find((o) => Math.abs(o.x - x) < (o.w + w) / 2 && Math.abs(o.y - y) < 15);
        while (bate() && y < HEIGHT - 8) y += 15;
        colocados.push({ x, y, w });
        g.lx = x;
        g.ly = y;
      });

    return { pontos, grupos };
  }, [dados, width]);

  if (carregando) {
    return (
      <section className="panel">
        <header className="panel-head">
          <h3>Grupos de clima</h3>
          <p className="panel-sub">Agrupando as faixas por semelhança de tags…</p>
        </header>
        <div className="skeleton" style={{ height: 180, borderRadius: 16 }} />
      </section>
    );
  }

  if (!dados || (!dados.clusters.length && !dados.note)) return null;

  function onMove(e) {
    if (!plot) return;
    const r = e.currentTarget.getBoundingClientRect();
    const mx = e.clientX - r.left;
    const my = e.clientY - r.top;
    let near = null;
    let best = 18;
    for (const p of plot.pontos) {
      const d = Math.hypot(p.px - mx, p.py - my);
      if (d < best) {
        best = d;
        near = p;
      }
    }
    setHover(near);
  }

  const destaque = hover ? hover.k : ativo;

  return (
    <section className="panel">
      <header className="panel-head">
        <h3>Grupos de clima</h3>
        <p className="panel-sub">
          {dados.clusters.length > 0
            ? `${dados.k} grupos de faixas com tags parecidas. O nome de cada grupo são as tags que mais o distinguem do resto da playlist.`
            : "Não deu para separar grupos nesta playlist."}
        </p>
      </header>

      {dados.note && <p className="cluster-note">{dados.note}</p>}

      {dados.clusters.length > 0 && (
        <div className="cluster-layout">
          <ul className="cluster-list">
            {dados.clusters.map((c, i) => (
              <li key={c.id}>
                <button
                  type="button"
                  className={`cluster-card${destaque != null && destaque !== i ? " is-dim" : ""}${destaque === i ? " is-active" : ""}`}
                  onMouseEnter={() => setAtivo(i)}
                  onMouseLeave={() => setAtivo(null)}
                  onFocus={() => setAtivo(i)}
                  onBlur={() => setAtivo(null)}
                >
                  <svg width="18" height="18" className="cluster-key" aria-hidden="true">
                    <Marker shape={SHAPES[i % SHAPES.length]} x={9} y={9} r={5} fill={SERIES[i % SERIES.length]} />
                  </svg>
                  <span className="cluster-body">
                    <span className="cluster-label">{c.label}</span>
                    <span className="cluster-count">{plural(c.size, "faixa", "faixas")}</span>
                    <span className="cluster-tags">{c.top_tags.slice(0, 4).join(", ")}</span>
                    <span className="cluster-samples">{c.sample_tracks.slice(0, 3).join(", ")}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>

          <div className="cluster-chart" ref={wrapRef}>
            {plot && (
              <>
                <svg
                  width={width}
                  height={HEIGHT}
                  role="img"
                  aria-label={`Mapa de ${dados.points.length} faixas em ${dados.k} grupos de clima.`}
                  onMouseMove={onMove}
                  onMouseLeave={() => setHover(null)}
                  className="cluster-plot"
                >
                  <defs>
                    {plot.grupos.map((g) => (
                      <radialGradient key={g.id} id={`halo-${g.id}`}>
                        <stop offset="0" stopColor={SERIES[g.k % SERIES.length]} stopOpacity="0.26" />
                        <stop offset="1" stopColor={SERIES[g.k % SERIES.length]} stopOpacity="0" />
                      </radialGradient>
                    ))}
                  </defs>

                  {plot.grupos.map((g) => (
                    <ellipse
                      key={g.id}
                      cx={g.cx}
                      cy={g.cy}
                      rx={g.rx * 1.25}
                      ry={g.ry * 1.25}
                      fill={`url(#halo-${g.id})`}
                      className={`cluster-halo${destaque != null && destaque !== g.k ? " is-dim" : ""}`}
                    />
                  ))}

                  {plot.pontos.map((p) => (
                    <g
                      key={p.track_id}
                      className={`cluster-point${destaque != null && destaque !== p.k ? " is-dim" : ""}`}
                    >
                      <Marker
                        shape={SHAPES[p.k % SHAPES.length]}
                        x={p.px}
                        y={p.py}
                        r={hover === p ? 6 : 4.5}
                        fill={SERIES[p.k % SERIES.length]}
                      />
                    </g>
                  ))}

                  {plot.grupos.map((g) => (
                    <text
                      key={`t-${g.id}`}
                      x={g.lx}
                      y={g.ly}
                      textAnchor="middle"
                      className={`cluster-plot-label${destaque != null && destaque !== g.k ? " is-dim" : ""}`}
                    >
                      {g.label}
                    </text>
                  ))}
                </svg>

                <ChartTooltip visible={hover != null} x={hover?.px ?? 0} y={(hover?.py ?? 0) - 10} width={width}>
                  {hover && (
                    <>
                      <span className="viz-tooltip-kicker">{dados.clusters[hover.k]?.label}</span>
                      <span className="viz-tooltip-title">{nomes.get(hover.track_id)?.name ?? "Faixa"}</span>
                      {nomes.get(hover.track_id) && (
                        <span className="viz-tooltip-sub">{nomes.get(hover.track_id).artists.join(", ")}</span>
                      )}
                    </>
                  )}
                </ChartTooltip>
              </>
            )}
            <p className="cluster-chart-note">
              Cada marca é uma faixa. Faixas próximas no mapa têm tags parecidas, mas a distância
              não tem escala.
              {dados.silhouette !== null && (
                <>
                  {" "}
                  {dados.silhouette < 0.25
                    ? "Os grupos se sobrepõem bastante."
                    : "Os grupos estão razoavelmente separados."}
                </>
              )}
            </p>
          </div>
        </div>
      )}
    </section>
  );
}
