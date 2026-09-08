import React from "react";
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
    </div>
  );
}
