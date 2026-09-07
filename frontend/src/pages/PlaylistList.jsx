import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";

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

export default function PlaylistList() {
  const [playlists, setPlaylists] = useState(null);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    api
      .listPlaylists()
      .then(setPlaylists)
      .catch(() => setError("Não foi possível carregar suas playlists."));
  }, []);

  const filtered = useMemo(() => {
    if (!playlists) return null;
    const q = query.trim().toLowerCase();
    if (!q) return playlists;
    return playlists.filter((p) => p.name.toLowerCase().includes(q));
  }, [playlists, query]);

  return (
    <div className="container">
      <div className="page-head">
        <div>
          <h2 className="page-title">Suas playlists</h2>
          {playlists && (
            <p className="muted page-sub">
              {playlists.length} {playlists.length === 1 ? "playlist" : "playlists"} na sua conta
            </p>
          )}
        </div>
        {playlists && playlists.length > 0 && (
          <input
            className="search"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filtrar por nome…"
            aria-label="Filtrar playlists por nome"
          />
        )}
      </div>

      {error && <div className="error-banner">{error}</div>}

      {!playlists && !error && (
        <div className="grid">
          {Array.from({ length: 8 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      )}

      {filtered?.length === 0 && (
        <p className="muted">Nenhuma playlist encontrada para “{query}”.</p>
      )}

      <div className="grid">
        {filtered?.map((p, i) => (
          <Link
            key={p.id}
            to={`/playlists/${p.id}`}
            className="card fade-in-up"
            style={{ animationDelay: `${Math.min(i, 11) * 35}ms` }}
          >
            <div className="card-art">
              {p.image ? (
                <img src={p.image} alt={p.name} loading="lazy" />
              ) : (
                <div className="card-art-empty" aria-hidden="true" />
              )}
              <span className="card-badge">{p.track_count}</span>
            </div>
            <div className="card-body">
              <p className="card-title">{p.name}</p>
              <p className="card-sub">
                {p.track_count} músicas · {p.owner}
              </p>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
