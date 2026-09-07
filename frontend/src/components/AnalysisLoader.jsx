import React, { useEffect, useRef, useState } from "react";

// Roughly in the order the backend actually works, with some editorial licence.
const PHRASES = [
  "Pedindo suas músicas ao Spotify…",
  "Contando as faixas nos dedos…",
  "Perguntando ao Last.fm que gênero é esse…",
  "Consultando a comunidade faixa por faixa…",
  "Separando rock de rock progressivo (tarefa delicada)…",
  "Discutindo se isso aqui é indie mesmo…",
  "Fingindo saber a diferença entre house e deep house…",
  "Traduzindo “vibe” para taxonomia musical…",
  "Empilhando subgêneros que ninguém pediu…",
  "Julgando seu gosto musical — com carinho…",
  "Procurando aquela faixa que você não assume que ouve…",
  "Montando os gráficos…",
  "Só mais um pouquinho, o Last.fm está pensando…",
];

const PHRASE_MS = 2800;
const TICK_MS = 200;

export default function AnalysisLoader() {
  const [phrase, setPhrase] = useState(0);
  const [progress, setProgress] = useState(6);
  const started = useRef(Date.now());

  useEffect(() => {
    const id = setInterval(() => {
      // Stop before the end: the bar completes only when the data actually lands.
      setPhrase((p) => (p + 1) % PHRASES.length);
    }, PHRASE_MS);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const id = setInterval(() => {
      const elapsed = (Date.now() - started.current) / 1000;
      // Asymptotic creep — fast at first, never quite reaching 100%.
      setProgress(Math.min(94, 100 * (1 - Math.exp(-elapsed / 6))));
    }, TICK_MS);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="analysis-loader">
      <div className="pulse-bars" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
      </div>

      <div
        className="progress-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(progress)}
        aria-label="Progresso da análise"
      >
        <div className="progress-fill" style={{ width: `${progress}%` }} />
      </div>

      <p className="loader-phrase" key={phrase} aria-live="polite">
        {PHRASES[phrase]}
      </p>
      <p className="loader-hint muted">
        Playlists grandes levam alguns segundos — depois disso fica em cache e abre rápido.
      </p>
    </div>
  );
}
