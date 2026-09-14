import React, { useEffect, useRef } from "react";
<<<<<<< HEAD
import { usePlayer } from "../PlayerContext.jsx";

const ACCENT_BRIGHT = "#22c55e";
const GRID = "#2a2a35";

/**
 * Desenha a forma de onda e o espectro do que está tocando.
 *
 * Não é dono do áudio: lê o `AnalyserNode` do PlayerContext, para que a barra
 * de rodapé e esta tela reflitam a mesma reprodução.
 */
export default function Waveform({ track }) {
  const { analyserRef, playing, track: atual, playTrack, toggle, time, duration, seek, erro } =
    usePlayer();
  const canvasRef = useRef(null);
  const rafRef = useRef(null);

  const estaAqui = atual?.track_id === track.track_id;
  const tocandoEsta = estaAqui && playing;

  function draw() {
    const canvas = canvasRef.current;
    const analyser = analyserRef.current;
    // Se o grafo ainda não existe, tenta no próximo quadro em vez de encerrar o
    // laço — desistir deixaria o canvas preto para sempre.
    if (!canvas || !analyser) {
      rafRef.current = requestAnimationFrame(draw);
      return;
    }

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }

    const g = canvas.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);

    g.strokeStyle = GRID;
    g.lineWidth = 1;
    g.beginPath();
    g.moveTo(0, h / 2);
    g.lineTo(w, h / 2);
    g.stroke();

    // Espectro ao fundo: graves à esquerda, agudos à direita.
    const freq = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(freq);
    const bars = 64;
    const step = Math.floor(freq.length / bars);
    const barW = w / bars;
    for (let i = 0; i < bars; i++) {
      let soma = 0;
      for (let j = 0; j < step; j++) soma += freq[i * step + j];
      const media = soma / step / 255;
      const barH = media * h * 0.85;
      g.fillStyle = `rgba(25, 164, 74, ${0.1 + media * 0.28})`;
      g.fillRect(i * barW + 1, h - barH, barW - 2, barH);
    }

    // A onda no domínio do tempo, por cima.
    const wave = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(wave);
    g.lineWidth = 2;
    g.strokeStyle = ACCENT_BRIGHT;
    g.beginPath();
    const slice = w / wave.length;
    for (let i = 0; i < wave.length; i++) {
      const v = wave[i] / 128 - 1;
      const y = h / 2 + v * (h / 2) * 0.92;
      i === 0 ? g.moveTo(i * slice, y) : g.lineTo(i * slice, y);
    }
    g.stroke();

    rafRef.current = requestAnimationFrame(draw);
  }

  // Anima só enquanto esta faixa toca: um rAF parado gastaria CPU à toa.
  useEffect(() => {
    if (tocandoEsta) {
      rafRef.current = requestAnimationFrame(draw);
    } else if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [tocandoEsta]);

  const t = estaAqui ? time : 0;
  const d = estaAqui ? duration : 0;
  const pct = d ? (t / d) * 100 : 0;

  return (
    <div className="player">
      <canvas
        ref={canvasRef}
        className="player-canvas"
        role="img"
        aria-label={`Visualização do áudio de ${track.name}`}
      />

      <div className="player-controls">
        <button
          className="player-play"
          onClick={() => (estaAqui ? toggle() : playTrack(track))}
          aria-label={tocandoEsta ? "Pausar" : "Reproduzir"}
        >
          {tocandoEsta ? (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" />
            </svg>
          ) : (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M8 5.5v13l11-6.5z" />
            </svg>
          )}
        </button>

        <div
          className="player-seek"
          onClick={(e) => {
            if (!estaAqui) return;
            const r = e.currentTarget.getBoundingClientRect();
            seek(((e.clientX - r.left) / r.width) * d);
          }}
          role="slider"
          aria-label="Posição da faixa"
          aria-valuemin={0}
          aria-valuemax={Math.round(d)}
          aria-valuenow={Math.round(t)}
          tabIndex={0}
        >
          <div className="player-seek-fill" style={{ width: `${pct}%` }} />
        </div>

        <span className="player-time tabular">
          {fmt(t)} / {fmt(d)}
        </span>
      </div>

      {erro && estaAqui && <p className="player-error">{erro}</p>}
    </div>
  );
}

function fmt(s) {
  if (!Number.isFinite(s)) return "0:00";
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}
=======

const PLAYED = "#1db954";
const UNPLAYED = "#3a3a48";
const BAR_W = 2;
const GAP = 1;
const MIN_H = 2; // trecho em silêncio ainda desenha um traço, senão a onda "some"

/**
 * Onda real da prévia: cada coluna é o pico do áudio naquele trecho, e a parte
 * já tocada fica verde. Clicar salta para o ponto correspondente.
 *
 * Enquanto os picos não chegam (o mp3 ainda está sendo decodificado) desenha uma
 * barra de progresso lisa — o som já está tocando, então mostrar nada seria pior.
 */
export default function Waveform({ peaks, progress, onSeek }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const dpr = window.devicePixelRatio || 1;
    const { width, height } = canvas.getBoundingClientRect();
    if (!width || !height) return;

    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const mid = height / 2;

    if (!peaks) {
      const track = 3;
      ctx.fillStyle = UNPLAYED;
      ctx.fillRect(0, mid - track / 2, width, track);
      ctx.fillStyle = PLAYED;
      ctx.fillRect(0, mid - track / 2, width * progress, track);
      return;
    }

    const step = BAR_W + GAP;
    const columns = Math.floor(width / step);
    const playedUntil = progress * columns;

    for (let i = 0; i < columns; i++) {
      // Reamostra os picos para o número de colunas que cabe de fato.
      const peak = peaks[Math.floor((i / columns) * peaks.length)] || 0;
      const h = Math.max(peak * (height - 2), MIN_H);
      ctx.fillStyle = i <= playedUntil ? PLAYED : UNPLAYED;
      ctx.fillRect(i * step, mid - h / 2, BAR_W, h);
    }
  }, [peaks, progress]);

  const handleSeek = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    onSeek?.((e.clientX - rect.left) / rect.width);
  };

  const handleKey = (e) => {
    if (e.key === "ArrowRight") onSeek?.(Math.min(1, progress + 0.05));
    else if (e.key === "ArrowLeft") onSeek?.(Math.max(0, progress - 0.05));
    else return;
    e.preventDefault();
  };

  return (
    <div
      className="waveform"
      onClick={handleSeek}
      onKeyDown={handleKey}
      role="slider"
      tabIndex={0}
      aria-label="Posição na prévia"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(progress * 100)}
    >
      <canvas ref={canvasRef} className="waveform-canvas" />
    </div>
  );
}
>>>>>>> 159c84aa20a29c88dffa974f84d744e63bdf7cf5
