import React, { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api.js";
import SubgenreBars from "../components/SubgenreBars.jsx";
import DistributionBarChart from "../components/DistributionBarChart.jsx";
import TopArtistsChart from "../components/TopArtistsChart.jsx";
import TrackTable from "../components/TrackTable.jsx";
import ClusterPanel from "../components/ClusterPanel.jsx";
import BpmChart from "../components/BpmChart.jsx";
import AnalysisLoader from "../components/AnalysisLoader.jsx";
import ChatWidget from "../components/ChatWidget.jsx";
import BackLink from "../components/BackLink.jsx";
import GenreFlow, { FLOW_SERIES_LIMIT } from "../charts/GenreFlow.jsx";
import { NEUTRAL, SERIES, pct } from "../charts/chartKit.js";

// Fora do componente: o GenreFlow memoriza o desenho por esta referência.
const leanOf = (t) => (t.subgenre_lean ? [t.subgenre_lean] : []);

function Stat({ value, label }) {
  return (
    <div className="stat">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}

export default function PlaylistDetail() {
  const { id } = useParams();
  const [analysis, setAnalysis] = useState(null);
  const [error, setError] = useState(null);
  const [selectedSub, setSelectedSub] = useState(null);
  const [chatAvailable, setChatAvailable] = useState(false);

  useEffect(() => {
    setAnalysis(null);
    setError(null);
    setSelectedSub(null);
    api
      .getPlaylistAnalysis(id)
      .then(setAnalysis)
      // 403, 404 e 429 vêm com uma explicação do backend que vale mostrar; o
      // resto vira a frase genérica.
      .catch((e) =>
        setError(
          [403, 404, 429].includes(e.status)
            ? e.message
            : "Não foi possível analisar essa playlist.",
        ),
      );
  }, [id]);

  useEffect(() => {
    api
      .chatStatus()
      .then((s) => setChatAvailable(s.available))
      .catch(() => setChatAvailable(false));
  }, []);

  // A cor segue o gênero: o mesmo gênero tem a mesma cor no fluxo e nas barras.
  const colorFor = useMemo(() => {
    if (!analysis || analysis.tracks.length < 6) return null;
    const inFlow = new Map(
      analysis.genre_distribution.slice(0, FLOW_SERIES_LIMIT).map((g, i) => [g.label, SERIES[i]]),
    );
    return (label) => inFlow.get(label) ?? NEUTRAL;
  }, [analysis]);

  // O caminho dos subgêneros usa as mesmas faixas-por-rótulo que o blend: conta
  // direto o subgenre_lean, para as cinco séries e o "outros" baterem com ele.
  const subFlowDistribution = useMemo(() => {
    if (!analysis) return [];
    const counts = new Map();
    analysis.tracks.forEach((t) => {
      if (t.subgenre_lean) counts.set(t.subgenre_lean, (counts.get(t.subgenre_lean) ?? 0) + 1);
    });
    return (analysis.subgenre_bars ?? [])
      .map((b) => ({ label: b.label, count: counts.get(b.label) ?? 0 }))
      .filter((g) => g.count > 0)
      .sort((a, b) => b.count - a.count);
  }, [analysis]);

  if (error) {
    return (
      <div className="container">
        <BackLink to="/playlists" />
        <div className="error-banner" role="alert">
          {error}
        </div>
      </div>
    );
  }

  if (!analysis) {
    return (
      <div className="container">
        <BackLink to="/playlists" />
        <AnalysisLoader />
      </div>
    );
  }

  const {
    playlist,
    tracks,
    genre_distribution,
    top_artists,
    average_bpm,
    tracks_missing_genre,
    tracks_missing_bpm,
  } = analysis;

  const subgenre_distribution = analysis.subgenre_distribution ?? [];
  const subgenreBars = analysis.subgenre_bars ?? [];
  // Análises antigas não têm o blend: as barras caem para a contagem por faixa
  // e perdem o filtro, que depende de subgenre_lean.
  const hasBlend = subgenreBars.length > 0;
  const barRows = hasBlend
    ? subgenreBars
    : subgenre_distribution.map((g) => ({ label: g.label, confident: g.count, unsure: 0 }));

  const identified = playlist.track_count - tracks_missing_genre;
  const minutes = Math.round(tracks.reduce((s, t) => s + t.duration_ms, 0) / 60000);
  const duration = minutes >= 60 ? `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}` : `${minutes} min`;
  // Com um gênero só (um álbum inteiro, ou uma playlist toda de psytrance), o
  // caminho dos gêneros vira uma linha reta em 100%, sem nada para mostrar.
  const singleGenre = genre_distribution.length <= 1;
  const distinctLeans = new Set(tracks.map((t) => t.subgenre_lean).filter(Boolean)).size;
  // Sem variedade de gênero, o caminho dos subgêneros é o que ainda tem história.
  const showSubFlow = singleGenre && distinctLeans >= 2;

  return (
    <>
      <div className="container page-enter">
        <BackLink to="/playlists" />

        <section className="hero">
          {playlist.image && (
            <div className="hero-backdrop" style={{ backgroundImage: `url(${playlist.image})` }} aria-hidden="true" />
          )}
          {playlist.image ? (
            <img className="hero-art" src={playlist.image} alt="" />
          ) : (
            <div className="hero-art hero-art-empty" aria-hidden="true" />
          )}
          <div className="hero-body">
            <h1 className="hero-title">{playlist.name}</h1>
            <p className="hero-meta">
              {playlist.owner ? `Playlist de ${playlist.owner}` : "Playlist"}, {duration} de música
            </p>
            <div className="stat-row">
              <Stat value={playlist.track_count} label="faixas" />
              <Stat value={genre_distribution.length} label="gêneros" />
              {subgenre_distribution.length > 0 && <Stat value={subgenre_distribution.length} label="subgêneros" />}
              <Stat value={pct(identified, playlist.track_count)} label="com gênero identificado" />
              {average_bpm != null && <Stat value={Math.round(average_bpm)} label="BPM médio" />}
            </div>
          </div>
        </section>

        {tracks_missing_genre > 0 && (
          <p className="note">
            {tracks_missing_genre} de {playlist.track_count} faixas ficaram sem gênero: nem o artista
            nem a faixa têm tags no Last.fm.
          </p>
        )}

        {!singleGenre && (
          <GenreFlow tracks={tracks} genreDistribution={genre_distribution} trackCount={playlist.track_count} />
        )}

        {showSubFlow && (
          <GenreFlow
            tracks={tracks}
            genreDistribution={subFlowDistribution}
            trackCount={playlist.track_count}
            labelsOf={leanOf}
            title="O caminho dos subgêneros"
            subtitle="Da primeira à última faixa, na ordem da playlist. A altura de cada linha é a parcela daquele subgênero naquele trecho. Passe o mouse para ver faixa a faixa; clique na legenda para isolar um subgênero."
          />
        )}

        {/* Sem subgênero próprio, o painel sairia vazio: gêneros ocupa a linha sozinho. */}
        <div className={barRows.length > 0 ? "charts-grid" : undefined}>
          <DistributionBarChart
            data={genre_distribution}
            total={playlist.track_count}
            title="Gêneros"
            subtitle={
              singleGenre ? "Tags do artista no Last.fm." : "Tags do artista no Last.fm. As cores são as mesmas do caminho acima."
            }
            colorFor={colorFor}
          />
          {barRows.length > 0 && (
            <SubgenreBars
              bars={barRows}
              total={playlist.track_count}
              onSelect={hasBlend ? setSelectedSub : null}
              selected={selectedSub}
            />
          )}
        </div>

        <div className="charts-grid charts-grid-wide">
          <BpmChart tracks={tracks} averageBpm={average_bpm} missing={tracks_missing_bpm} />
          <TopArtistsChart data={top_artists} total={playlist.track_count} />
        </div>

        <ClusterPanel playlistId={id} tracks={tracks} />

        <TrackTable
          tracks={tracks}
          filter={selectedSub ? { subgenre: selectedSub } : null}
          onClearFilter={() => setSelectedSub(null)}
        />
      </div>

      {/* Fora do .page-enter: a animação de entrada vira bloco de contenção
          e prenderia o botão fixo ao fim da página em vez da tela. */}
      {chatAvailable && (
        <ChatWidget
          scope="playlist"
          playlistId={id}
          subjectName={playlist.name}
          suggestions={[
            "Como você descreveria o clima desta playlist?",
            "Quais artistas aparecem com mais frequência aqui?",
            "Alguma faixa desta lista foge do padrão de gênero?",
          ]}
        />
      )}
    </>
  );
}
