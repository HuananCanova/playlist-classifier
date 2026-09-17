import React, { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { usePlayer } from "../PlayerContext.jsx";

function formatDuration(ms) {
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

export function PlayIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M8 5.5v13l11-6.5z" />
    </svg>
  );
}

export function PauseIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" />
    </svg>
  );
}

/** Três barras que dançam enquanto a faixa da linha toca — o estado, não enfeite. */
function PlayingBars() {
  return (
    <span className="eq" aria-hidden="true">
      <span />
      <span />
      <span />
    </span>
  );
}

export default function TrackTable({ tracks }) {
  const [query, setQuery] = useState("");
  const { track: current, playing, playTrack: play } = usePlayer();

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
          <h3>Faixas</h3>
          <p className="panel-sub">
            {query ? `${filtered.length} de ${tracks.length} faixas` : `${tracks.length} faixas`}, com
            as tags de gênero de cada uma
          </p>
        </div>
        <input
          className="search"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Buscar faixa, artista ou tag"
          aria-label="Buscar faixas"
        />
      </header>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th className="col-play">
                <span className="sr-only">Prévia</span>
              </th>
              <th className="col-art">
                <span className="sr-only">Capa</span>
              </th>
              <th>Faixa</th>
              <th className="col-artists">Artistas</th>
              <th className="col-bpm">BPM</th>
              <th className="col-duration">Duração</th>
              <th>Subgêneros</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((t) => {
              const isCurrent = current?.track_id === t.track_id;
              return (
                <tr key={t.track_id} className={isCurrent ? "row-active" : ""}>
                  <td className="col-play">
                    {t.preview_url || t.deezer_id ? (
                      <button
                        className="play-btn"
                        onClick={() => play(t)}
                        aria-label={isCurrent && playing ? `Pausar ${t.name}` : `Tocar prévia de ${t.name}`}
                      >
                        {isCurrent && playing ? <PauseIcon size={12} /> : <PlayIcon size={12} />}
                      </button>
                    ) : (
                      <span className="play-btn play-btn-off" title="Sem prévia no Deezer">
                        <PlayIcon size={12} />
                      </span>
                    )}
                  </td>
                  <td className="col-art">
                    <Link to={`/faixa/${t.track_id}`} className="track-art-link" tabIndex={-1} aria-hidden="true">
                      {t.image && <img className="track-art" src={t.image} alt="" loading="lazy" />}
                    </Link>
                  </td>
                  <td className="track-name">
                    <Link to={`/faixa/${t.track_id}`}>{t.name}</Link>
                    {isCurrent && playing && <PlayingBars />}
                    <span className="track-artists-inline">{t.artists.join(", ")}</span>
                  </td>
                  <td className="muted col-artists">{t.artists.join(", ")}</td>
                  <td className="col-bpm tabular">
                    {t.bpm != null ? Math.round(t.bpm) : <span className="muted">—</span>}
                  </td>
                  <td className="muted col-duration tabular">{formatDuration(t.duration_ms)}</td>
                  <td className="col-tags">
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
              );
            })}
          </tbody>
        </table>

        {filtered.length === 0 && (
          <p className="muted panel-empty">Nenhuma faixa com “{query}” no nome, artista ou tag.</p>
        )}
      </div>
    </section>
  );
}
