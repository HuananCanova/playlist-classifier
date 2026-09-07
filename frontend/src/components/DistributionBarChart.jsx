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

const ROW_HEIGHT = 34;
const CHART_PADDING = 48;
const AXIS_WIDTH = 132;
// Kept short enough that a tick never wraps to a second line inside AXIS_WIDTH.
const MAX_LABEL = 16;

// Single hue: these bars compare magnitude across nominal categories, so colour
// carries no extra meaning — one series, one colour (validated against the
// #17171f panel surface: inside the dark lightness band, contrast >= 3:1).
const BAR = "#19a44a";
const BAR_HOVER = "#22c55e";
const GRID = "#2a2a35";
const AXIS_INK = "#9a9aa5";

function truncate(label) {
  return label.length > MAX_LABEL ? `${label.slice(0, MAX_LABEL - 1)}…` : label;
}

function ChartTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const { label, count } = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <span className="chart-tooltip-label">{label}</span>
      <span className="chart-tooltip-value">
        {count} {count === 1 ? "música" : "músicas"}
      </span>
    </div>
  );
}

/**
 * Horizontal bars — the right form for part-to-whole with many long-named
 * categories. (A pie clipped its radial labels and couldn't fit these names.)
 */
export default function DistributionBarChart({ data, title, subtitle, limit = 10 }) {
  const [hovered, setHovered] = React.useState(null);

  const top = data.slice(0, limit);
  const rest = data.slice(limit);
  const restTotal = rest.reduce((sum, d) => sum + d.count, 0);
  const rows = restTotal > 0 ? [...top, { label: "outros", count: restTotal }] : top;

  // Recharts lays categories out in array order, top to bottom — the data already
  // arrives sorted descending, so the largest sits at the top where it belongs.
  const chartData = rows;
  const height = Math.max(chartData.length * ROW_HEIGHT + CHART_PADDING, 160);

  return (
    <section className="panel">
      <header className="panel-head">
        <h3>{title}</h3>
        {subtitle && <p className="panel-sub">{subtitle}</p>}
      </header>

      {chartData.length === 0 ? (
        <p className="muted panel-empty">Sem dados suficientes.</p>
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 4, right: 28, bottom: 4, left: 0 }}
            barCategoryGap={8}
            onMouseLeave={() => setHovered(null)}
          >
            <CartesianGrid stroke={GRID} horizontal={false} />
            <XAxis
              type="number"
              allowDecimals={false}
              stroke={GRID}
              tick={{ fill: AXIS_INK, fontSize: 11 }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              type="category"
              dataKey="label"
              width={AXIS_WIDTH}
              stroke={GRID}
              tick={{ fill: AXIS_INK, fontSize: 12 }}
              tickLine={false}
              axisLine={false}
              tickFormatter={truncate}
              interval={0}
            />
            <Tooltip
              content={<ChartTooltip />}
              cursor={{ fill: "rgba(255,255,255,0.04)" }}
            />
            <Bar
              dataKey="count"
              radius={[0, 4, 4, 0]}
              maxBarSize={22}
              isAnimationActive
              animationDuration={520}
              onMouseEnter={(_, i) => setHovered(i)}
            >
              {chartData.map((_, i) => (
                <Cell key={i} fill={hovered === i ? BAR_HOVER : BAR} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </section>
  );
}
