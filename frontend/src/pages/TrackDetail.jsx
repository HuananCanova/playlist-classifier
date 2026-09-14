import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import Waveform from "../components/Waveform.jsx";
import AudioMetrics from "../components/AudioMetrics.jsx";
import ChatWidget from "../components/ChatWidget.jsx";
import { SearchHit } from "./Search.jsx";
import BackLink from "../components/BackLink.jsx";

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
  const [similares, setSimilares] = useState([]);

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

  // Lista vazia é o caso normal, não um erro: a faixa só está no índice depois
  // que a playlist que a contém foi analisada.
  useEffect(() => {
    setSimilares([]);
    api
      .getSimilarTracks(id)
      .then(setSimilares)
      .catch(() => setSimilares([]));
  }, [id]);

  if (error) {
    return (
      <div className="container">
        <BackLink onClick={() => navigate(-1)} />
        <div className="error-banner">{error}</div>
      </div>
    );
  }

  if (!track) {
    return (
      <div className="container">
        <BackLink onClick={() => navigate(-1)} />
        <div className="hero hero-skeleton" aria-busy="true">
          <div className="skeleton hero-art" />
          <div className="hero-body">
            <div className="skeleton skeleton-line" style={{ width: "60%", height: 30 }} />
            <div className="skeleton skeleton-line skeleton-line-short" />
          </div>
        </div>
      </div>
    );
  }

  const minutos = Math.floor(track.duration_ms / 60000);
  const segundos = String(Math.floor((track.duration_ms % 60000) / 1000)).padStart(2, "0");

  return (
    <>
      <div className="container page-enter">
        <BackLink onClick={() => navigate(-1)} />

        <section className="hero">
          {track.image && (
            <div className="hero-backdrop" style={{ backgroundImage: `url(${track.image})` }} aria-hidden="true" />
          )}
          {track.image ? (
            <img className="hero-art" src={track.image} alt="" />
          ) : (
            <div className="hero-art hero-art-empty" aria-hidden="true" />
          )}
          <div className="hero-body">
            <h1 className="hero-title">{track.name}</h1>
            <p className="hero-meta">
              {track.artists.join(", ")}
              {track.album ? <span className="hero-meta-album">do álbum {track.album}</span> : null}
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
                <a className="btn btn-ghost btn-sm" href={track.spotify_url} target="_blank" rel="noreferrer">
                  Abrir no Spotify
                </a>
              )}
              {track.deezer_url && (
                <a className="btn btn-ghost btn-sm" href={track.deezer_url} target="_blank" rel="noreferrer">
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
              Prévia de 30 segundos do Deezer. A onda e o espectro são desenhados enquanto toca.
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
                Medidas direto do som da prévia, não copiadas de um catálogo
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

        {similares.length > 0 && (
          <section className="panel">
            <header className="panel-head">
              <h3>Parecidas com esta</h3>
              <p className="panel-sub">
                Por proximidade de tags, entre as faixas que você já analisou
              </p>
            </header>
            <ul className="hit-list">
              {similares.map((h) => (
                <li key={h.track_id}>
                  <SearchHit hit={h} />
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      {/* Fora do .page-enter: a animação de entrada vira bloco de contenção
          e prenderia o botão fixo ao fim da página em vez da tela. */}
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
    </>
  );
}
