import React from "react";

/**
 * Tooltip HTML posicionado sobre um gráfico SVG. Fica dentro do contêiner do
 * gráfico e troca de lado perto da borda direita em vez de vazar da tela.
 */
export default function ChartTooltip({ x, y, width, children, visible = true }) {
  if (!visible) return null;
  const flip = x > width - 220;
  return (
    <div
      className={`viz-tooltip${flip ? " viz-tooltip-flip" : ""}`}
      style={{ left: x, top: y }}
      role="presentation"
    >
      {children}
    </div>
  );
}
