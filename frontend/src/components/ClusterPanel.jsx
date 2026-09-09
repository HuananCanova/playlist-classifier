import React, { useEffect, useState } from "react";
import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api.js";

// Uma cor por grupo, no máximo MAX_K do backend. Verde do app primeiro, o resto
// escolhido para se separar bem em fundo escuro.
const CORES = ["#1db954", "#4f8ff7", "#e0954f", "#c678dd", "#4fd1c5", "#f2777a"];

export default function ClusterPanel({ playlistId }) {
  const [dados, setDados] = useState(null);
  const [carregando, setCarregando] = useState(true);

  useEffect(() => {
    let ativo = true;
    setCarregando(true);
    api
      .getPlaylistClusters(playlistId)
      .then((d) => ativo && setDados(d))
      .catch(() => ativo && setDados(null))
      .finally(() => ativo && setCarregando(false));
    return () => {
      ativo = false;
    };
  }, [playlistId]);

  if (carregando) {
    return (
      <section className="panel">
        <header className="panel-head">
          <h3>Grupos de clima</h3>
        </header>
        <p className="spinner-text">Agrupando as faixas…</p>
      </section>
    );
  }

  if (!dados || (!dados.clusters.length && !dados.note)) return null;

  const nomePorId = new Map();
  dados.clusters.forEach((c) => nomePorId.set(c.id, c.label));

  const series = dados.clusters.map((c) => ({
    id: c.id,
    label: c.label,
    pontos: dados.points
      .filter((p) => p.cluster === c.id)
      .map((p) => ({ x: p.x, y: p.y, grupo: nomePorId.get(p.cluster) })),
  }));

  return (
    <section className="panel">
      <header className="panel-head">
        <h3>Grupos de clima</h3>
        <p className="panel-sub">
          {dados.clusters.length > 0
            ? `${dados.k} grupos por k-means sobre as tags. As etiquetas são as tags que mais distinguem cada grupo do resto da playlist.`
            : "Não deu para separar grupos nesta playlist."}
        </p>
      </header>

      {dados.note && <p className="cluster-note">{dados.note}</p>}

      {dados.clusters.length > 0 && (
        <>
          <ul className="cluster-list">
            {dados.clusters.map((c, i) => (
              <li key={c.id} className="cluster-card">
                <span
                  className="cluster-dot"
                  style={{ background: CORES[i % CORES.length] }}
                  aria-hidden="true"
                />
                <div className="cluster-body">
                  <span className="cluster-label">{c.label}</span>
                  <span className="cluster-count">
                    {c.size} faixa{c.size === 1 ? "" : "s"}
                  </span>
                  <span className="cluster-tags">{c.top_tags.join(" · ")}</span>
                  <span className="cluster-samples">{c.sample_tracks.slice(0, 3).join(" · ")}</span>
                </div>
              </li>
            ))}
          </ul>

          <div className="cluster-chart">
            <ResponsiveContainer width="100%" height={260}>
              <ScatterChart margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
                <CartesianGrid stroke="#2a2a35" strokeDasharray="3 3" />
                {/* Os eixos são as duas primeiras componentes do SVD: úteis para
                    ver separação, sem unidade que signifique algo. */}
                <XAxis type="number" dataKey="x" hide />
                <YAxis type="number" dataKey="y" hide />
                <Tooltip
                  cursor={{ stroke: "#3a3a48" }}
                  contentStyle={{
                    background: "#17171f",
                    border: "1px solid #2a2a35",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  formatter={(_v, _n, item) => [item?.payload?.grupo ?? "", "grupo"]}
                />
                {series.map((s, i) => (
                  <Scatter
                    key={s.id}
                    name={s.label}
                    data={s.pontos}
                    fill={CORES[i % CORES.length]}
                    fillOpacity={0.85}
                  />
                ))}
              </ScatterChart>
            </ResponsiveContainer>
            <p className="cluster-chart-note">
              Cada ponto é uma faixa, projetada em 2D só para desenhar. Proximidade
              na tela indica proximidade real, mas a distância exata não tem escala.
              {dados.silhouette !== null && (
                <> Silhueta {dados.silhouette.toFixed(2)}
                  {dados.silhouette < 0.25 ? " — grupos bem sobrepostos." : " — separação razoável."}
                </>
              )}
            </p>
          </div>
        </>
      )}
    </section>
  );
}
