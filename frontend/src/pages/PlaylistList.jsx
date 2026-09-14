import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatWait } from "../api.js";
import { useAuth } from "../AuthContext.jsx";

function SkeletonCard() {
  return (
    <div className="card card-skeleton" aria-hidden="true">
      <div className="skeleton skeleton-art" />
      <div className="card-body">
        <div className="skeleton skeleton-line" />
        <div className="skeleton skeleton-line skeleton-line-short" />
      </div>
    </div>
  );
}

function CoverPlaceholder({ name }) {
  // Sem capa: um relevo de onda gerado do nome, para cada playlist ter a sua.
  let seed = 0;
  for (const ch of name) seed = (seed * 31 + ch.charCodeAt(0)) % 9973;
  const bars = Array.from({ length: 11 }, (_, i) => 18 + (((seed >> (i % 8)) + i * 7) % 46));
  return (
    <svg className="card-art-empty" viewBox="0 0 100 100" aria-hidden="true">
      {bars.map((h, i) => (
        <rect key={i} x={9 + i * 7.6} y={50 - h / 2} width="3.4" height={h} rx="1.7" />
      ))}
    </svg>
  );
}

export default function PlaylistList() {
  const { user } = useAuth();
  const [playlists, setPlaylists] = useState(null);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback((refresh = false) => {
    setError(null);
    // Ao atualizar, a grade anterior fica na tela esmaecida em vez de piscar
    // para esqueleto e voltar.
    if (refresh) setRefreshing(true);
    else setPlaylists(null);
    api
      .listPlaylists({ refresh })
      .then(setPlaylists)
      .catch((e) =>
        setError({
          message: e.message || "Não foi possível carregar suas playlists.",
          // 429 é temporário: aqui a ação certa é tentar de novo, não recarregar tudo.
          canRetry: e.status === 429 || e.status === 502,
          retryAfter: e.retryAfter,
        }),
      )
      .finally(() => setRefreshing(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(() => {
    if (!playlists) return null;
    const q = query.trim().toLowerCase();
    if (!q) return playlists;
    return playlists.filter((p) => p.name.toLowerCase().includes(q));
  }, [playlists, query]);

  const totalTracks = playlists?.reduce((sum, p) => sum + p.track_count, 0) ?? 0;

  return (
    <div className="container page-enter">
      <div className="page-head">
        <div>
          <h1 className="page-title">Suas playlists</h1>
          {playlists && (
            <p className="page-sub">
              {playlists.length} {playlists.length === 1 ? "playlist" : "playlists"} com{" "}
              {totalTracks.toLocaleString("pt-BR")} faixas. Aparecem só as que você criou ou
              colabora, porque são as únicas que o Spotify deixa analisar.
            </p>
          )}
        </div>
        {playlists && playlists.length > 0 && (
          <div className="page-actions">
            <input
              className="search"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filtrar por nome"
              aria-label="Filtrar playlists por nome"
            />
            <button
              className="btn btn-ghost"
              onClick={() => load(true)}
              disabled={refreshing}
              title="Busca de novo no Spotify, ignorando o cache de 5 minutos"
            >
              <RefreshIcon spinning={refreshing} />
              {refreshing ? "Atualizando" : "Atualizar"}
            </button>
          </div>
        )}
      </div>

      {error && (
        <div className="error-banner" role="alert">
          <span>{error.message}</span>
          {error.canRetry && (
            <button className="btn btn-ghost btn-sm" onClick={() => load()}>
              Tentar de novo
              {error.retryAfter ? ` em ${formatWait(error.retryAfter)}` : ""}
            </button>
          )}
        </div>
      )}

      {!playlists && !error && (
        <div className="grid">
          {Array.from({ length: 8 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      )}

      {playlists?.length === 0 && (
        <div className="empty-state">
          <h2>Nenhuma playlist para analisar</h2>
          <p>
            Crie uma playlist no Spotify, ou peça para entrar como colaborador numa, e depois
            clique em Atualizar.
          </p>
        </div>
      )}

      {playlists?.length > 0 && filtered?.length === 0 && (
        <p className="muted">Nenhuma playlist com “{query}” no nome.</p>
      )}

      <div className={`grid${refreshing ? " is-stale" : ""}`}>
        {filtered?.map((p) => {
          const ownerShown = p.owner && p.owner !== user?.display_name;
          return (
            <Link key={p.id} to={`/playlists/${p.id}`} className="card">
              <div className="card-art">
                {p.image ? (
                  <img src={p.image} alt="" loading="lazy" />
                ) : (
                  <CoverPlaceholder name={p.name} />
                )}
              </div>
              <div className="card-body">
                <p className="card-title">{p.name}</p>
                <p className="card-sub">
                  {p.track_count} {p.track_count === 1 ? "faixa" : "faixas"}
                  {ownerShown && <span className="card-owner">de {p.owner}</span>}
                </p>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

function RefreshIcon({ spinning }) {
  return (
    <svg
      className={`icon${spinning ? " icon-spin" : ""}`}
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
