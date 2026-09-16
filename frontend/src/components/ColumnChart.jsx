import React, { useMemo, useState } from "react";
import ChartTooltip from "../charts/ChartTooltip.jsx";
import { SERIES, niceMax, useMounted, useWidth } from "../charts/chartKit.js";

const HEIGHT = 190;
const PAD_TOP = 22;
const AXIS_H = 24;
const GAP = 2;
const RADIUS = 4;

/** Retângulo com só o topo arredondado: a base fica presa na linha de zero. */
function columnPath(x, y, w, h) {
  const r = Math.min(RADIUS, w / 2, h);
  if (h <= 0) return "";
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

/**
 * Colunas para uma escala ordenada — décadas, meses. Uma série, uma cor: a
 * altura já mostra o valor, pintar por valor só repetiria a informação.
 *
 * `data`: [{ key, label, tooltip, count, major?, majorLabel? }]. `label` vai no
 * eixo (os rótulos rareiam sozinhos quando não cabem); `tooltip` é o título
 * completo do hover. Quando os rótulos ficariam tão esparsos que "mar." já não
 * diria de que ano é, o eixo passa a mostrar só as colunas `major` (ex.: janeiro)
 * com `majorLabel` (ex.: o ano).
 */
export default function ColumnChart({ data, unit = ["faixa", "faixas"], ariaLabel }) {
  const [wrapRef, width] = useWidth();
  const mounted = useMounted();
  const [hover, setHover] = useState(null);

  const model = useMemo(() => {
    if (!width || data.length === 0) return null;
    const max = niceMax(Math.max(...data.map((d) => d.count), 1));
    const plotH = HEIGHT - PAD_TOP - AXIS_H;
    const step = width / data.length;
    const colW = Math.max(step - GAP, 1);

    // Um rótulo a cada `every` colunas, para nenhum encostar no vizinho.
    const longest = Math.max(...data.map((d) => d.label.length));
    const every = Math.max(1, Math.ceil((longest * 7 + 10) / step));

    let ticks;
    if (every > 6 && data.some((d) => d.major)) {
      ticks = [];
      let lastX = -Infinity;
      data.forEach((d, i) => {
        const text = d.majorLabel ?? d.label;
        const x = i * step + step / 2;
        if (d.major && x - lastX >= text.length * 7 + 12) {
          ticks.push({ key: d.key, x, text, anchor: i === 0 ? "start" : "middle" });
          lastX = x;
        }
      });
    } else {
      ticks = data
        .map((d, i) => ({ key: d.key, x: i * step + step / 2, text: d.label, anchor: i === 0 && step < 30 ? "start" : "middle", i }))
        .filter((t) => t.i % every === 0);
    }

    let peak = 0;
    data.forEach((d, i) => {
      if (d.count > data[peak].count) peak = i;
    });

    const cols = data.map((d, i) => {
      const h = (d.count / max) * plotH;
      return { ...d, i, x: i * step + GAP / 2, w: colW, y: PAD_TOP + plotH - h, h };
    });

    return { max, plotH, step, cols, ticks, peak };
  }, [data, width]);

  if (data.length === 0) {
    return <p className="muted panel-empty">Sem dados suficientes.</p>;
  }

  function onMove(e) {
    if (!model) return;
    const r = e.currentTarget.getBoundingClientRect();
    const i = Math.min(data.length - 1, Math.max(0, Math.floor((e.clientX - r.left) / model.step)));
    setHover(model.cols[i]);
  }

  const total = data.reduce((s, d) => s + d.count, 0);

  return (
    <div className="colchart-wrap" ref={wrapRef}>
      {model && (
        <>
          <svg
            width={width}
            height={HEIGHT}
            role="img"
            aria-label={ariaLabel}
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
              <path
                key={c.key}
                d={columnPath(c.x, c.y, c.w, c.h)}
                fill={SERIES[0]}
                className="colchart-col"
                style={{
                  opacity: hover && hover.i !== c.i ? 0.45 : 1,
                  transform: mounted ? "scaleY(1)" : "scaleY(0)",
                  transitionDelay: `${Math.min(c.i, 40) * 12}ms`,
                }}
              />
            ))}

            <line x1={0} x2={width} y1={PAD_TOP + model.plotH} y2={PAD_TOP + model.plotH} className="viz-baseline" />

            {/* Rótulo direto só no pico: o resto fica no hover. */}
            {model.cols[model.peak].count > 0 && !hover && (
              <text
                x={Math.min(Math.max(model.cols[model.peak].x + model.cols[model.peak].w / 2, 14), width - 14)}
                y={model.cols[model.peak].y - 6}
                textAnchor="middle"
                className="colchart-peak"
              >
                {model.cols[model.peak].count.toLocaleString("pt-BR")}
              </text>
            )}

            <g className="viz-axis" transform={`translate(0, ${HEIGHT - 6})`}>
              {model.ticks.map((t) => (
                <text key={t.key} x={t.anchor === "start" ? t.x - model.step / 2 : t.x} textAnchor={t.anchor}>
                  {t.text}
                </text>
              ))}
            </g>
          </svg>

          <ChartTooltip
            visible={hover != null}
            x={hover ? hover.x + hover.w / 2 : 0}
            y={hover ? Math.max(hover.y, PAD_TOP + 20) : 0}
            width={width}
          >
            {hover && (
              <>
                <span className="viz-tooltip-kicker">{hover.tooltip ?? hover.label}</span>
                <span className="viz-tooltip-title">
                  {hover.count.toLocaleString("pt-BR")} {hover.count === 1 ? unit[0] : unit[1]}
                </span>
                {total > 0 && (
                  <span className="viz-tooltip-sub">
                    {Math.round((hover.count / total) * 100)}% do total
                  </span>
                )}
              </>
            )}
          </ChartTooltip>
        </>
      )}
    </div>
  );
}
