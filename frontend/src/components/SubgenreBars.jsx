import React from "react";
import { Link } from "react-router-dom";
import { SERIES, pct, useMounted } from "../charts/chartKit.js";

const LIMIT = 12;

function oneDecimal(v) {
  return v.toFixed(1).replace(".", ",");
}

/**
 * Barras de subgênero com a parte incerta: cada linha soma as parcelas do
 * blend das faixas, e a parte clara é a que vem de faixas incertas. O nome
 * leva à página do subgênero; a barra seleciona o filtro da tabela de faixas.
 *
 * `bars`: [{ label, confident, unsure }] em faixas-equivalentes. Sem
 * `onSelect`, a barra só mostra (análises antigas não têm blend para filtrar).
 */
export default function SubgenreBars({ bars, total, onSelect = null, selected = null }) {
  const mounted = useMounted();
  const rows = bars.slice(0, LIMIT);
  const max = Math.max(...rows.map((r) => r.confident + r.unsure), 0.01);
  const hasUnsure = rows.some((r) => r.unsure > 0);
  const color = SERIES[0];

  return (
    <section className="panel">
      <header className="panel-head">
        <h3>Subgêneros</h3>
        <p className="panel-sub">
          Cada faixa divide uma unidade entre os subgêneros que a evidência aponta.
          {onSelect && " Clique numa barra para ver as faixas."}
        </p>
      </header>

      <ol className="bars subbars">
        {rows.map((r) => {
          const value = r.confident + r.unsure;
          const isSelected = selected === r.label;
          const share = pct(value, total);
          const text = `${oneDecimal(value)} faixas, ${share} da playlist`;
          const body = (
            <>
              <span className="bar-track" aria-hidden="true">
                <span
                  className="bar-fill subbar-fill"
                  style={{
                    width: `${(value / max) * 100}%`,
                    transform: mounted ? "scaleX(1)" : "scaleX(0)",
                  }}
                >
                  <span className="subbar-part" style={{ width: `${value ? (r.confident / value) * 100 : 0}%`, background: color }} />
                  <span
                    className="subbar-part subbar-unsure"
                    style={{ width: `${value ? (r.unsure / value) * 100 : 0}%`, background: color }}
                  />
                </span>
              </span>
              <span className="bar-value" aria-hidden="true">
                <span className="tabular">{oneDecimal(value)}</span>
                <span className="bar-share tabular">{share}</span>
              </span>
            </>
          );
          return (
            <li key={r.label} className={`bar-row subbar-row${isSelected ? " is-selected" : ""}`}>
              <Link className="bar-label subbar-link" to={`/subgenero/${encodeURIComponent(r.label)}`} title={r.label}>
                {r.label}
              </Link>
              {onSelect ? (
                <button
                  type="button"
                  className="subbar-hit"
                  aria-pressed={isSelected}
                  aria-label={`${isSelected ? "Limpar filtro de" : "Filtrar por"} ${r.label}: ${text}`}
                  onClick={() => onSelect(isSelected ? null : r.label)}
                >
                  {body}
                </button>
              ) : (
                <span className="subbar-hit" role="img" aria-label={`${r.label}: ${text}`}>
                  {body}
                </span>
              )}
            </li>
          );
        })}
      </ol>

      <p className="panel-foot muted">
        {hasUnsure && "Parte clara = incerta, de faixas em que a evidência não bastou. "}
        Valores em faixas-equivalentes (a soma das parcelas); porcentagens sobre as {total} faixas.
      </p>
    </section>
  );
}
