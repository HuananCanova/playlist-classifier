import React from "react";
<<<<<<< HEAD
import { useNavigate, useLocation } from "react-router-dom";
import { usePlayer } from "../PlayerContext.jsx";

function fmt(s) {
  if (!Number.isFinite(s)) return "0:00";
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

/**
 * Barra fixa no rodapé com a faixa atual, no formato do Spotify.
 *
 * Clicar na barra abre a página da faixa; clicar nos controles não navega —
 * cada controle interrompe a propagação do clique.
 */
export default function NowPlayingBar() {
  const { track, playing, time, duration, toggle, seek, stop } = usePlayer();
  const navigate = useNavigate();
  const location = useLocation();

  if (!track) return null;

  const naPaginaDaFaixa = location.pathname === `/faixa/${track.track_id}`;
  const pct = duration ? (time / duration) * 100 : 0;

  const abrir = () => {
    if (!naPaginaDaFaixa) navigate(`/faixa/${track.track_id}`);
  };

  return (
    <div
      className={`nowplaying${naPaginaDaFaixa ? " nowplaying-current" : ""}`}
      onClick={abrir}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          abrir();
        }
      }}
      role={naPaginaDaFaixa ? undefined : "link"}
      tabIndex={naPaginaDaFaixa ? undefined : 0}
      aria-label={naPaginaDaFaixa ? undefined : `Abrir a página de ${track.name}`}
    >
      {track.image ? (
        <img className="nowplaying-art" src={track.image} alt="" />
      ) : (
        <div className="nowplaying-art nowplaying-art-empty" aria-hidden="true" />
      )}

      <div className="nowplaying-meta">
        <p className="nowplaying-title">{track.name}</p>
        <p className="nowplaying-artist">{(track.artists || []).join(", ")}</p>
      </div>

      {/* stopPropagation nos controles: clicar em play não deve abrir a página. */}
      <div className="nowplaying-controls" onClick={(e) => e.stopPropagation()}>
        <button
          className="nowplaying-play"
          onClick={toggle}
          aria-label={playing ? "Pausar" : "Reproduzir"}
        >
          {playing ? (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" />
            </svg>
          ) : (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M8 5.5v13l11-6.5z" />
            </svg>
          )}
        </button>

        <span className="nowplaying-time tabular">{fmt(time)}</span>

        <div
          className="nowplaying-seek"
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            seek(((e.clientX - r.left) / r.width) * duration);
          }}
          role="slider"
          aria-label="Posição da faixa"
          aria-valuemin={0}
          aria-valuemax={Math.round(duration)}
          aria-valuenow={Math.round(time)}
          tabIndex={0}
        >
          <div className="nowplaying-seek-fill" style={{ width: `${pct}%` }} />
        </div>

        <span className="nowplaying-time tabular">{fmt(duration)}</span>

        <button className="nowplaying-close" onClick={stop} aria-label="Fechar o player">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M18 6 6 18M6 6l12 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </button>
      </div>
=======
import { usePlayer } from "../PlayerContext.jsx";
import Waveform from "./Waveform.jsx";

const PREVIEW_SECONDS = 30;

function formatTime(seconds) {
  const s = Math.max(0, Math.round(seconds));
  return `0:${String(s % 60).padStart(2, "0")}`;
}

/**
 * Barra fixa no rodapé com a faixa que está tocando.
 *
 * A onda vive aqui, e não em cada linha da tabela, de propósito: desenhar a onda
 * exige baixar e decodificar o mp3, então uma por linha baixaria a playlist
 * inteira de uma vez. Aqui só a faixa tocando paga esse custo.
 */
export default function NowPlayingBar() {
  const { track, playing, peaks, progress, error, toggle, seek, close } = usePlayer();
  if (!track) return null;

  const elapsed = progress * PREVIEW_SECONDS;

  return (
    <div className="now-playing" role="region" aria-label="Tocando agora">
      {track.image && <img className="np-art" src={track.image} alt="" />}

      <div className="np-meta">
        <span className="np-title" title={track.name}>{track.name}</span>
        <span className="np-artist muted">{track.artists.join(", ")}</span>
      </div>

      <button
        className="np-play"
        onClick={toggle}
        aria-label={playing ? "Pausar" : "Tocar"}
      >
        {playing ? "❚❚" : "▶"}
      </button>

      <div className="np-wave">
        {error ? (
          <span className="muted np-error">{error}</span>
        ) : (
          <Waveform peaks={peaks} progress={progress} onSeek={seek} />
        )}
      </div>

      <span className="np-time tabular muted">
        {formatTime(elapsed)} / 0:30
      </span>

      {track.bpm != null && <span className="np-bpm">{Math.round(track.bpm)} BPM</span>}

      {track.deezer_url && (
        <a className="np-source muted" href={track.deezer_url} target="_blank" rel="noreferrer">
          Deezer
        </a>
      )}

      <button className="np-close" onClick={close} aria-label="Fechar player">
        ✕
      </button>
>>>>>>> 159c84aa20a29c88dffa974f84d744e63bdf7cf5
    </div>
  );
}
