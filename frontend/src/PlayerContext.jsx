import React, { createContext, useContext, useEffect, useRef, useState } from "react";

const PlayerContext = createContext(null);

/**
 * Dono único do áudio do app.
 *
 * O elemento <audio> e o grafo da Web Audio API vivem aqui, e não nas telas: a
 * barra de "tocando agora" e o visualizador da página da faixa precisam ser o
 * mesmo player. Dois elementos <audio> tocariam sobrepostos, e o
 * `createMediaElementSource` só pode ser chamado uma vez por elemento.
 */
export function PlayerProvider({ children }) {
  const audioRef = useRef(null);
  const ctxRef = useRef(null);
  const analyserRef = useRef(null);
  const sourceRef = useRef(null);

  const [track, setTrack] = useState(null); // {track_id, name, artists, image, preview_url}
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [erro, setErro] = useState(null);

  // O grafo só pode nascer a partir de um gesto do usuário (política de
  // autoplay), por isso é montado no primeiro play e reaproveitado depois.
  function ensureGraph() {
    if (ctxRef.current) return true;
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const ctx = new AudioCtx();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.75;
      const source = ctx.createMediaElementSource(audioRef.current);
      source.connect(analyser);
      analyser.connect(ctx.destination);
      ctxRef.current = ctx;
      analyserRef.current = analyser;
      sourceRef.current = source;
      return true;
    } catch {
      setErro("Não foi possível analisar o áudio neste navegador.");
      return false;
    }
  }

  async function playTrack(novo) {
    if (!novo?.preview_url) {
      setErro("Esta faixa não tem prévia de áudio.");
      return;
    }
    setErro(null);

    const mesmaFaixa = track?.track_id === novo.track_id;
    if (!mesmaFaixa) {
      setTrack(novo);
      setTime(0);
      audioRef.current.src = novo.preview_url;
    }
    if (!ensureGraph()) return;
    if (ctxRef.current.state === "suspended") await ctxRef.current.resume();

    try {
      await audioRef.current.play();
    } catch {
      setErro("O navegador bloqueou a reprodução.");
    }
  }

  async function toggle() {
    const audio = audioRef.current;
    if (!audio || !track) return;
    if (!audio.paused) {
      audio.pause();
      return;
    }
    if (!ensureGraph()) return;
    if (ctxRef.current.state === "suspended") await ctxRef.current.resume();
    try {
      await audio.play();
    } catch {
      setErro("O navegador bloqueou a reprodução.");
    }
  }

  function seek(segundos) {
    if (audioRef.current && Number.isFinite(segundos)) {
      audioRef.current.currentTime = segundos;
    }
  }

  function stop() {
    audioRef.current?.pause();
    setTrack(null);
    setTime(0);
  }

  useEffect(() => () => ctxRef.current?.close(), []);

  return (
    <PlayerContext.Provider
      value={{ track, playing, time, duration, erro, analyserRef, playTrack, toggle, seek, stop }}
    >
      {/* Fica fora das rotas: navegar entre telas não pode interromper a música. */}
      <audio
        ref={audioRef}
        crossOrigin="anonymous"  /* exigido para a Web Audio API ler outra origem */
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration || 0)}
        onError={() => setErro("Não consegui carregar o áudio de prévia.")}
      />
      {children}
    </PlayerContext.Provider>
  );
}

export function usePlayer() {
  const ctx = useContext(PlayerContext);
  if (!ctx) throw new Error("usePlayer precisa estar dentro de PlayerProvider");
  return ctx;
}
