import React, { useEffect, useRef } from "react";
import { usePlayer } from "../PlayerContext.jsx";
import { PauseIcon, PlayIcon } from "./TrackTable.jsx";

const ACCENT_BRIGHT = "#7ee8a4";
const GRID = "rgba(255, 255, 255, 0.07)";

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
      const grad = g.createLinearGradient(0, h - barH, 0, h);
      grad.addColorStop(0, `rgba(30, 215, 96, ${0.18 + media * 0.5})`);
      grad.addColorStop(1, "rgba(30, 215, 96, 0.02)");
      g.fillStyle = grad;
      const bx = i * barW + 1.5;
      const bw = Math.max(barW - 3, 1);
      const radius = Math.min(3, bw / 2);
      g.beginPath();
      if (g.roundRect) g.roundRect(bx, h - barH, bw, barH, [radius, radius, 0, 0]);
      else g.rect(bx, h - barH, bw, barH);
      g.fill();
    }

    // A onda no domínio do tempo, por cima.
    const wave = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(wave);
    g.lineWidth = 2;
    g.lineJoin = "round";
    g.shadowColor = "rgba(30, 215, 96, 0.7)";
    g.shadowBlur = 12;
    g.strokeStyle = ACCENT_BRIGHT;
    g.beginPath();
    const slice = w / wave.length;
    for (let i = 0; i < wave.length; i++) {
      const v = wave[i] / 128 - 1;
      const y = h / 2 + v * (h / 2) * 0.92;
      i === 0 ? g.moveTo(i * slice, y) : g.lineTo(i * slice, y);
    }
    g.stroke();
    g.shadowBlur = 0;

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
          {tocandoEsta ? <PauseIcon size={20} /> : <PlayIcon size={20} />}
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
