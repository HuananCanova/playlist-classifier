import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

const PlayerContext = createContext(null);

// Quantas colunas a onda desenha. 160 dá densidade suficiente numa barra de
// ~520px sem virar uma mancha sólida.
const PEAK_BUCKETS = 160;

/** Um AudioContext para a página inteira: os navegadores limitam quantos existem
 *  ao mesmo tempo, e criar um por faixa estoura esse teto numa playlist longa. */
let sharedAudioContext = null;
function getAudioContext() {
  if (!sharedAudioContext) {
    const Ctor = window.AudioContext || window.webkitAudioContext;
    if (!Ctor) return null;
    sharedAudioContext = new Ctor();
  }
  return sharedAudioContext;
}

/** Decodifica o mp3 da prévia e reduz a N picos para desenhar.
 *  Roda em paralelo à reprodução — o áudio toca pelo <audio>, que faz stream;
 *  isto aqui é só o visual, e chegar um pouco depois não atrasa o som. */
async function loadPeaks(url, signal) {
  const ctx = getAudioContext();
  if (!ctx) return null;

  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`preview ${res.status}`);
  const buf = await res.arrayBuffer();
  const audio = await ctx.decodeAudioData(buf);

  const data = audio.getChannelData(0);
  const block = Math.floor(data.length / PEAK_BUCKETS) || 1;
  const peaks = new Float32Array(PEAK_BUCKETS);

  let max = 0;
  for (let i = 0; i < PEAK_BUCKETS; i++) {
    let peak = 0;
    const start = i * block;
    for (let j = 0; j < block; j++) {
      const v = Math.abs(data[start + j] || 0);
      if (v > peak) peak = v;
    }
    peaks[i] = peak;
    if (peak > max) max = peak;
  }

  // Normaliza: prévias vêm com volumes bem diferentes, e sem isso uma faixa
  // baixinha desenharia uma linha reta.
  if (max > 0) for (let i = 0; i < PEAK_BUCKETS; i++) peaks[i] /= max;
  return peaks;
}

export function PlayerProvider({ children }) {
  const audioRef = useRef(null);
  const abortRef = useRef(null);

  const [track, setTrack] = useState(null);
  const [playing, setPlaying] = useState(false);
  const [peaks, setPeaks] = useState(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState(null);

  if (!audioRef.current && typeof Audio !== "undefined") {
    audioRef.current = new Audio();
    audioRef.current.preload = "auto";
  }

  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;

    const onTime = () => setProgress(el.duration ? el.currentTime / el.duration : 0);
    const onEnd = () => { setPlaying(false); setProgress(0); };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onErr = () => { setError("Não deu para tocar a prévia."); setPlaying(false); };

    el.addEventListener("timeupdate", onTime);
    el.addEventListener("ended", onEnd);
    el.addEventListener("play", onPlay);
    el.addEventListener("pause", onPause);
    el.addEventListener("error", onErr);
    return () => {
      el.removeEventListener("timeupdate", onTime);
      el.removeEventListener("ended", onEnd);
      el.removeEventListener("play", onPlay);
      el.removeEventListener("pause", onPause);
      el.removeEventListener("error", onErr);
    };
  }, []);

  const play = useCallback(async (next) => {
    const el = audioRef.current;
    if (!el || !next?.preview_url) return;

    // Mesma faixa: é play/pause, não recarrega nem redesenha a onda.
    if (track && next.track_id === track.track_id) {
      if (el.paused) el.play().catch(() => {});
      else el.pause();
      return;
    }

    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    setTrack(next);
    setPeaks(null);
    setProgress(0);
    setError(null);

    el.src = next.preview_url;
    el.currentTime = 0;
    // Um AudioContext criado antes de qualquer gesto do usuário nasce suspenso.
    getAudioContext()?.resume?.().catch(() => {});
    el.play().catch(() => setError("Não deu para tocar a prévia."));

    try {
      const p = await loadPeaks(next.preview_url, ac.signal);
      if (!ac.signal.aborted) setPeaks(p);
    } catch (e) {
      // Sem onda o player ainda toca — degrada para uma barra de progresso lisa.
      if (e.name !== "AbortError") setPeaks(null);
    }
  }, [track]);

  const toggle = useCallback(() => {
    const el = audioRef.current;
    if (!el || !track) return;
    if (el.paused) el.play().catch(() => {});
    else el.pause();
  }, [track]);

  const seek = useCallback((ratio) => {
    const el = audioRef.current;
    if (!el || !el.duration) return;
    el.currentTime = Math.max(0, Math.min(1, ratio)) * el.duration;
    setProgress(ratio);
  }, []);

  const close = useCallback(() => {
    abortRef.current?.abort();
    const el = audioRef.current;
    if (el) { el.pause(); el.removeAttribute("src"); el.load(); }
    setTrack(null);
    setPeaks(null);
    setPlaying(false);
    setProgress(0);
  }, []);

  const value = useMemo(
    () => ({ track, playing, peaks, progress, error, play, toggle, seek, close,
             duration: audioRef.current?.duration || 0 }),
    [track, playing, peaks, progress, error, play, toggle, seek, close],
  );

  return <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>;
}

export function usePlayer() {
  const ctx = useContext(PlayerContext);
  if (!ctx) throw new Error("usePlayer precisa estar dentro de PlayerProvider");
  return ctx;
}
