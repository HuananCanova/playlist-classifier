import React from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Cell,
} from "recharts";

// Mesma decisão de cor dos outros gráficos: uma série só, uma cor só — aqui a
// altura já carrega a magnitude, e um degradê por faixa sugeriria uma segunda
// variável que não existe. (Validado contra o painel #17171f: contraste >= 3:1.)
const BAR = "#19a44a";
const BAR_HOVER = "#22c55e";
const GRID = "#2a2a35";
const AXIS_INK = "#9a9aa5";

function ChartTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const { label, count } = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <span className="chart-tooltip-label">{label} BPM</span>
      <span className="chart-tooltip-value">
        {count} {count === 1 ? "música" : "músicas"}
      </span>
    </div>
  );
}

/**
 * Histograma de andamento. Barras verticais e em ordem crescente de BPM — ao
 * contrário das outras distribuições, esta NÃO pode ser reordenada por
 * contagem: o eixo é uma escala contínua, e embaralhar destruiria a leitura de
 * onde a playlist se concentra.
 */
export default function BpmChart({ data, averageBpm, missing }) {
  const [hovered, setHovered] = React.useState(null);

  return (
    <section className="panel">
      <header className="panel-head">
        <h3>Andamento (BPM)</h3>
        <p className="panel-sub">
          {averageBpm != null
            ? `Média de ${Math.round(averageBpm)} BPM · dados do Deezer`
            : "Dados do Deezer"}
        </p>
      </header>

      {data.length === 0 ? (
        <p className="muted panel-empty">
          Nenhuma faixa desta playlist tem BPM no catálogo do Deezer.
        </p>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart
              data={data}
              margin={{ top: 8, right: 12, bottom: 4, left: 0 }}
              barCategoryGap={6}
              onMouseLeave={() => setHovered(null)}
            >
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis
                dataKey="label"
                stroke={GRID}
                tick={{ fill: AXIS_INK, fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                interval={0}
              />
              <YAxis
                allowDecimals={false}
                // Sem isto o Recharts arredonda o topo para folgado (máximo 2 ->
                // eixo até 4) e as barras ficam com metade da altura à toa.
                domain={[0, "dataMax"]}
                stroke={GRID}
                tick={{ fill: AXIS_INK, fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={32}
              />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
              <Bar
                dataKey="count"
                radius={[4, 4, 0, 0]}
                maxBarSize={56}
                isAnimationActive
                animationDuration={520}
                onMouseEnter={(_, i) => setHovered(i)}
              >
                {data.map((_, i) => (
                  <Cell key={i} fill={hovered === i ? BAR_HOVER : BAR} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>

          {missing > 0 && (
            <p className="muted panel-foot">
              {missing} {missing === 1 ? "música sem BPM" : "músicas sem BPM"} no Deezer —
              fora da contagem acima.
            </p>
          )}
        </>
      )}
    </section>
  );
}
