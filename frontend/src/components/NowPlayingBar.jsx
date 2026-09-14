import React from "react";
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
    </div>
  );
}
