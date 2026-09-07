import React from "react";
import DistributionBarChart from "./DistributionBarChart.jsx";

export default function TopArtistsChart({ data }) {
  return (
    <DistributionBarChart
      data={data}
      title="Artistas mais frequentes"
      subtitle="Quantas faixas da playlist cada artista assina"
      limit={12}
    />
  );
}
