import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api.js";
import DistributionBarChart from "../components/DistributionBarChart.jsx";
import TopArtistsChart from "../components/TopArtistsChart.jsx";
import TrackTable from "../components/TrackTable.jsx";
import AnalysisLoader from "../components/AnalysisLoader.jsx";

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

  useEffect(() => {
    setAnalysis(null);
    setError(null);
    api
      .getPlaylistAnalysis(id)
      .then(setAnalysis)
      .catch(() => setError("Não foi possível analisar essa playlist."));
  }, [id]);

  if (error) {
    return (
      <div className="container">
        <Link to="/playlists" className="back-link">
          ← Voltar
        </Link>
        <div className="error-banner">{error}</div>
      </div>
    );
  }

  if (!analysis) {
    return (
      <div className="container">
        <Link to="/playlists" className="back-link">
          ← Voltar
        </Link>
        <AnalysisLoader />
      </div>
    );
  }

  const {
    playlist,
    tracks,
    genre_distribution,
    subgenre_distribution,
    top_artists,
    tracks_missing_genre,
  } = analysis;

  const identified = playlist.track_count - tracks_missing_genre;

  return (
    <div className="container fade-in">
      <Link to="/playlists" className="back-link">
        ← Voltar
      </Link>

      <section className="hero">
        {playlist.image && (
          <img className="hero-art" src={playlist.image} alt={playlist.name} />
        )}
        <div className="hero-body">
          <p className="hero-eyebrow">Playlist</p>
          <h1 className="hero-title">{playlist.name}</h1>
          <p className="muted hero-meta">
            {playlist.track_count} músicas · por {playlist.owner}
          </p>
          <div className="stat-row">
            <Stat value={playlist.track_count} label="músicas" />
            <Stat value={genre_distribution.length} label="gêneros" />
            <Stat value={subgenre_distribution.length} label="subgêneros" />
            <Stat value={identified} label="classificadas" />
          </div>
        </div>
      </section>

      {tracks_missing_genre > 0 && (
        <p className="note">
          {tracks_missing_genre} de {playlist.track_count} músicas não têm gênero identificado
          (artista ou faixa sem tags no Last.fm).
        </p>
      )}

      <div className="charts-grid">
        <DistributionBarChart
          data={genre_distribution}
          title="Gêneros"
          subtitle="Tags do artista no Last.fm"
        />
        <DistributionBarChart
          data={subgenre_distribution}
          title="Subgêneros"
          subtitle="Tags da faixa no Last.fm, por música"
        />
      </div>

      <TopArtistsChart data={top_artists} />

      <TrackTable tracks={tracks} />
    </div>
  );
}
