import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import Waveform from "../components/Waveform.jsx";
import AudioMetrics from "../components/AudioMetrics.jsx";
import ChatWidget from "../components/ChatWidget.jsx";

function Stat({ value, label, hint }) {
  return (
    <div className="stat">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
      {hint && <span className="stat-hint">{hint}</span>}
    </div>
  );
}

export default function TrackDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [track, setTrack] = useState(null);
  const [error, setError] = useState(null);
  const [chatAvailable, setChatAvailable] = useState(false);

  useEffect(() => {
    setTrack(null);
    setError(null);
    api
      .getTrack(id)
      .then(setTrack)
      .catch(() => setError("Não foi possível carregar essa faixa."));
  }, [id]);

  useEffect(() => {
    api
      .chatStatus()
      .then((s) => setChatAvailable(s.available))
      .catch(() => setChatAvailable(false));
  }, []);

  if (error) {
    return (
      <div className="container">
        <button className="back-link" onClick={() => navigate(-1)}>
          ← Voltar
        </button>
        <div className="error-banner">{error}</div>
      </div>
    );
  }

  if (!track) {
    return (
      <div className="container">
        <button className="back-link" onClick={() => navigate(-1)}>
          ← Voltar
        </button>
        <p className="spinner-text" style={{ marginTop: 40 }}>
          Carregando a faixa…
        </p>
      </div>
    );
  }

  const minutos = Math.floor(track.duration_ms / 60000);
  const segundos = String(Math.floor((track.duration_ms % 60000) / 1000)).padStart(2, "0");

  return (
    <div className="container fade-in">
      <button className="back-link" onClick={() => navigate(-1)}>
        ← Voltar
      </button>

      <section className="hero">
        {track.image && <img className="hero-art" src={track.image} alt={track.name} />}
        <div className="hero-body">
          <p className="hero-eyebrow">Faixa</p>
          <h1 className="hero-title">{track.name}</h1>
          <p className="muted hero-meta">
            {track.artists.join(", ")}
            {track.album ? ` · ${track.album}` : ""}
          </p>

          <div className="stat-row">
            <Stat value={`${minutos}:${segundos}`} label="duração" />
            <Stat
              value={track.bpm ? Math.round(track.bpm) : "—"}
              label="BPM"
              hint={track.bpm ? "via Deezer" : "não catalogado"}
            />
            <Stat value={track.tags.length || "—"} label="tags" />
          </div>

          <div className="hero-links">
            {track.spotify_url && (
              <a className="btn btn-secondary btn-sm" href={track.spotify_url} target="_blank" rel="noreferrer">
                Abrir no Spotify
              </a>
            )}
            {track.deezer_url && (
              <a className="btn btn-secondary btn-sm" href={track.deezer_url} target="_blank" rel="noreferrer">
                Abrir no Deezer
              </a>
            )}
          </div>
        </div>
      </section>

      {track.match_confidence === "aproximada" && (
        <p className="note">
          A prévia e o BPM vêm de “{track.matched_title}” no Deezer, uma correspondência
          aproximada — pode não ser exatamente esta gravação.
        </p>
      )}

      <section className="panel">
        <header className="panel-head">
          <h3>Áudio</h3>
          <p className="panel-sub">
            Prévia de 30s do Deezer, com a forma de onda e o espectro desenhados em tempo real
          </p>
        </header>

        {track.preview_url ? (
          <Waveform track={track} />
        ) : (
          <p className="muted panel-empty">
            Não há prévia de áudio disponível para esta faixa.
          </p>
        )}
      </section>

      {track.preview_url && (
        <section className="panel">
          <header className="panel-head">
            <h3>Métricas do áudio</h3>
            <p className="panel-sub">
              Medidas das amostras da prévia — não são metadados do catálogo
            </p>
          </header>
          <AudioMetrics track={track} />
        </section>
      )}

      {track.tags.length > 0 && (
        <section className="panel">
          <header className="panel-head">
            <h3>Tags</h3>
            <p className="panel-sub">Da comunidade do Last.fm, para esta faixa</p>
          </header>
          <div>
            {track.tags.map((t) => (
              <span key={t} className="tag">
                {t}
              </span>
            ))}
          </div>
        </section>
      )}

      {chatAvailable && (
        <ChatWidget
          scope="track"
          trackId={track.track_id}
          subjectName={track.name}
          suggestions={[
            "O que as tags desta faixa sugerem sobre o estilo?",
            "Como você descreveria o clima desta música?",
            track.bpm
              ? `O BPM de ${Math.round(track.bpm)} indica um ritmo acelerado ou mais lento?`
              : "Por que o BPM pode estar indisponível para esta faixa?",
          ]}
        />
      )}
    </div>
  );
}
