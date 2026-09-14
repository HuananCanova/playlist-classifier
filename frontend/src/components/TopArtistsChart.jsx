import React from "react";
import DistributionBarChart from "./DistributionBarChart.jsx";

export default function TopArtistsChart({ data, total }) {
  return (
    <DistributionBarChart
      data={data}
      total={total}
      title="Artistas mais frequentes"
      subtitle="Quantas faixas da playlist cada artista assina"
      unit={["faixa", "faixas"]}
      limit={8}
    />
  );
}
