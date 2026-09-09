import React, { useEffect, useRef } from "react";
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
