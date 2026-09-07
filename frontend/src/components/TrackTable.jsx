import React, { useMemo, useState } from "react";

function formatDuration(ms) {
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

export default function TrackTable({ tracks }) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return tracks;
    return tracks.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.artists.join(" ").toLowerCase().includes(q) ||
        t.subgenre_tags.some((tag) => tag.toLowerCase().includes(q)),
    );
  }, [tracks, query]);

  return (
    <section className="panel">
      <header className="panel-head panel-head-row">
        <div>
          <h3>Músicas ({tracks.length})</h3>
          <p className="panel-sub">Tags de gênero de cada faixa</p>
        </div>
        <input
          className="search"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Buscar faixa, artista ou tag…"
          aria-label="Buscar faixas"
        />
      </header>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th className="col-art" />
              <th>Faixa</th>
              <th>Artista(s)</th>
              <th className="col-duration">Duração</th>
              <th>Gêneros / subgêneros</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((t) => (
              <tr key={t.track_id}>
                <td className="col-art">
                  {t.image && <img className="track-art" src={t.image} alt="" loading="lazy" />}
                </td>
                <td className="track-name">
                  {t.spotify_url ? (
                    <a href={t.spotify_url} target="_blank" rel="noreferrer">
                      {t.name}
                    </a>
                  ) : (
                    t.name
                  )}
                </td>
                <td className="muted">{t.artists.join(", ")}</td>
                <td className="muted col-duration tabular">{formatDuration(t.duration_ms)}</td>
                <td>
                  {t.subgenre_tags.length === 0 ? (
                    <span className="muted">—</span>
                  ) : (
                    t.subgenre_tags.map((tag) => (
                      <span key={tag} className="tag">
                        {tag}
                      </span>
                    ))
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {filtered.length === 0 && (
          <p className="muted panel-empty">Nenhuma faixa encontrada para “{query}”.</p>
        )}
      </div>
    </section>
  );
}
