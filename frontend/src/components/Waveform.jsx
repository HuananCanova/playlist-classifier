import React, { useEffect, useRef } from "react";

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
