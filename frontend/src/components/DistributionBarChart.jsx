import React, { useState } from "react";
import { NEUTRAL, SERIES, pct, plural, useMounted } from "../charts/chartKit.js";

/**
 * Barras horizontais: a forma certa para comparar muitas categorias de nome
 * longo. Desenhadas em HTML — o rótulo nunca é cortado por um eixo de largura
 * fixa, e cada linha é um alvo de hover inteiro, não só a barra.
 *
 * `colorFor(label)` deixa a página amarrar a cor à entidade (o mesmo gênero
 * tem a mesma cor aqui e no fluxo de gêneros). Sem ele, uma série só, uma
 * cor só: pintar por valor repetiria o que o comprimento já mostra.
 */
export default function DistributionBarChart({
  data,
  title,
  subtitle,
  total,
  limit = 10,
  unit = ["música", "músicas"],
  colorFor = null,
}) {
  const mounted = useMounted();
  const [hovered, setHovered] = useState(null);

  const top = data.slice(0, limit);
  const rest = data.slice(limit);
  const restTotal = rest.reduce((sum, d) => sum + d.count, 0);
  const rows =
    restTotal > 0
      ? [...top, { label: `${rest.length} outros`, count: restTotal, isRest: true }]
      : top;
  const max = Math.max(...rows.map((r) => r.count), 1);

  return (
    <section className="panel">
      <header className="panel-head">
        <h3>{title}</h3>
        {subtitle && <p className="panel-sub">{subtitle}</p>}
      </header>

      {rows.length === 0 ? (
        <p className="muted panel-empty">Sem dados suficientes.</p>
      ) : (
        <ol className={`bars${hovered != null ? " has-hover" : ""}`} onMouseLeave={() => setHovered(null)}>
          {rows.map((r, i) => {
            const color = r.isRest ? NEUTRAL : colorFor ? colorFor(r.label) : SERIES[0];
            const share = total ? pct(r.count, total) : null;
            return (
              <li
                key={r.label}
                className={`bar-row${hovered === i ? " is-hover" : ""}`}
                onMouseEnter={() => setHovered(i)}
                tabIndex={0}
                onFocus={() => setHovered(i)}
                onBlur={() => setHovered(null)}
                aria-label={`${r.label}: ${plural(r.count, unit[0], unit[1])}${share ? `, ${share} da playlist` : ""}`}
              >
                <span className="bar-label" title={r.label}>
                  {r.label}
                </span>
                <span className="bar-track" aria-hidden="true">
                  <span
                    className="bar-fill"
                    style={{
                      width: `${(r.count / max) * 100}%`,
                      background: color,
                      transform: mounted ? "scaleX(1)" : "scaleX(0)",
                    }}
                  />
                </span>
                <span className="bar-value" aria-hidden="true">
                  <span className="tabular">{r.count}</span>
                  {share && <span className="bar-share tabular">{share}</span>}
                </span>
              </li>
            );
          })}
        </ol>
      )}

      {total > 0 && rows.length > 0 && (
        <p className="panel-foot muted">
          Porcentagens sobre as {total} faixas. Uma faixa pode ter mais de uma tag, então a soma
          passa de 100%.
        </p>
      )}
    </section>
  );
}
