import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";

// Mesmo ritmo do painel de cobertura do perfil.
const POLL_MS = 2500;

const nf = new Intl.NumberFormat("pt-BR");

/**
 * Busca a evidência que falta (tags do Last.fm e BPM do Deezer) das faixas do
 * acervo. Some quando não há nada pendente; chama `onDone` quando um trabalho
 * que este painel acompanhou termina, para a página recarregar seus dados.
 */
export default function EnrichPanel({ onDone }) {
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef(null);
  const alive = useRef(true);
  const sawRunning = useRef(false);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  // Um único laço de consulta por vez: cada chamada cancela o timer anterior.
  const poll = useCallback(async () => {
    clearTimeout(timer.current);
    let next;
    try {
      next = await api.getEnrich();
    } catch {
      return; // o painel segue com o último estado; nada para insistir
    }
    if (!alive.current) return;
    clearTimeout(timer.current);
    setProgress(next);
    if (next.running) {
      sawRunning.current = true;
      timer.current = setTimeout(poll, POLL_MS);
    } else if (sawRunning.current) {
      sawRunning.current = false;
      onDoneRef.current?.();
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    poll();
    return () => {
      alive.current = false;
      clearTimeout(timer.current);
    };
  }, [poll]);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const next = await api.startEnrich();
      if (!alive.current) return;
      setProgress(next);
      sawRunning.current = true;
      poll();
    } catch (e) {
      if (alive.current) {
        setError(
          e.status === 429
            ? "Não consegui listar suas playlists agora (limite do Spotify). Tente de novo em alguns minutos."
            : e.message || "Não consegui iniciar a busca.",
        );
      }
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  async function stop() {
    try {
      const next = await api.stopEnrich();
      if (alive.current && next) setProgress(next);
    } catch {
      // parar é best-effort; a próxima consulta corrige o estado
    }
    poll();
  }

  if (!progress) return null;

  const running = Boolean(progress.running);
  const pending = progress.pending ?? 0;
  const errors = progress.errors ?? [];
  if (!running && pending === 0 && !error) return null;

  const minutes = Math.max(1, Math.round(progress.estimated_minutes ?? 1));

  return (
    <div className="coverage profile-coverage">
      {running ? (
        <div className="coverage-top">
          <div className="coverage-running" role="status">
            <span className="typing-dots" aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
            <span>
              {nf.format(progress.done ?? 0)} de {nf.format(progress.total ?? 0)}
            </span>
            {progress.current && <span className="coverage-current">{progress.current}</span>}
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={stop}>
            Parar
          </button>
        </div>
      ) : (
        <>
          <div className="coverage-top">
            <span className="coverage-label">
              <b>{nf.format(pending)}</b> {pending === 1 ? "faixa ainda sem evidência" : "faixas ainda sem evidência"}{" "}
              (tags do Last.fm separadas e BPM do Deezer). Leva ~{minutes} min e não usa o Spotify.
            </span>
            {pending > 0 && (
              <button type="button" className="btn btn-sm" onClick={start} disabled={busy}>
                Buscar evidência
              </button>
            )}
          </div>
          {errors.length > 0 && (
            <p className="coverage-errors">
              {errors.length} {errors.length === 1 ? "busca falhou" : "buscas falharam"}; rode de novo para tentar só
              essas.
            </p>
          )}
        </>
      )}
      {error && (
        <p className="coverage-errors" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
