import React, { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { pct, plural } from "../charts/chartKit.js";

// Quantos aparecem antes do "ver todos". Passa de perto da dobra sem virar uma
// lista sem fim numa playlist com 200 artistas.
const PREVIEW = 12;

/**
 * Todos os artistas da playlist, do que mais assina faixas ao que menos.
 *
 * Montado a partir das faixas que a página já tem — nenhuma chamada nova. O
 * `top_artists` da análise existe, mas vem cortado em 15 e sem os ids; aqui a
 * lista é inteira e cada linha leva à página do artista.
 */
export function buildArtistRows(tracks) {
  const byId = new Map();

  tracks.forEach((track) => {
    track.artists.forEach((name, i) => {
      // Sem id do Spotify o artista continua contando, só não vira link: a
      // chave cai para o nome para não fundir dois artistas homônimos com um
      // terceiro sem id.
      const id = track.artist_ids?.[i] || "";
      const key = id || `name:${name.toLowerCase()}`;
      const row = byId.get(key);
      if (row) {
        row.count += 1;
        row.tracks.push(track);
      } else {
        byId.set(key, { id, name, count: 1, tracks: [track] });
      }
    });
  });

  return [...byId.values()].sort(
    (a, b) => b.count - a.count || a.name.localeCompare(b.name, "pt-BR"),
  );
}

function ArtistRow({ row, total, max }) {
  const inner = (
    <>
      <span className="artist-row-name" title={row.name}>
        {row.name}
      </span>
      <span className="artist-row-track" aria-hidden="true">
        <span className="artist-row-fill" style={{ width: `${(row.count / max) * 100}%` }} />
      </span>
      <span className="artist-row-value tabular">
        {row.count}
        <span className="artist-row-share">{pct(row.count, total)}</span>
      </span>
    </>
  );

  const label = `${row.name}: ${plural(row.count, "faixa", "faixas")} nesta playlist`;

  // Sem id não há página para abrir — a linha continua na lista, só não clicável.
  return row.id ? (
    <Link className="artist-row is-link" to={`/artista/${row.id}`} aria-label={label}>
      {inner}
    </Link>
  ) : (
    <span className="artist-row" aria-label={label}>
      {inner}
    </span>
  );
}

export default function ArtistsPanel({ tracks, total }) {
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(false);

  const rows = useMemo(() => buildArtistRows(tracks), [tracks]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? rows.filter((r) => r.name.toLowerCase().includes(q)) : rows;
  }, [rows, query]);

  // A barra é sempre relativa ao maior da playlist, não ao maior do filtro:
  // senão filtrar mudaria o tamanho das barras e falsearia a comparação.
  const max = rows[0]?.count ?? 1;
  const searching = query.trim().length > 0;
  const visible = expanded || searching ? filtered : filtered.slice(0, PREVIEW);
  const hidden = filtered.length - visible.length;

  const soloists = rows.filter((r) => r.count === 1).length;

  return (
    <section className="panel">
      <header className="panel-head">
        <div className="panel-head-row">
          <h3>Artistas</h3>
          <span className="flow-scale">
            {plural(rows.length, "artista", "artistas")} nesta playlist
          </span>
        </div>
        <p className="panel-sub">
          Quantas faixas cada um assina. {soloists > 0 && `${soloists} aparecem uma vez só. `}
          Clique para ver o artista, com biografia, links e as faixas dele no seu acervo.
        </p>
      </header>

      {rows.length > PREVIEW && (
        <div className="artist-filter">
          <input
            type="search"
            className="search"
            placeholder="Filtrar artista por nome"
            aria-label="Filtrar artista por nome"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      )}

      {visible.length === 0 ? (
        <p className="muted panel-empty">Nenhum artista com esse nome nesta playlist.</p>
      ) : (
        <ol className="artist-rows">
          {visible.map((row) => (
            <li key={row.id || row.name}>
              <ArtistRow row={row} total={total} max={max} />
            </li>
          ))}
        </ol>
      )}

      {hidden > 0 && (
        <button type="button" className="btn btn-ghost btn-sm artist-more" onClick={() => setExpanded(true)}>
          Ver todos os {filtered.length} artistas
        </button>
      )}
      {expanded && !searching && rows.length > PREVIEW && (
        <button type="button" className="btn btn-ghost btn-sm artist-more" onClick={() => setExpanded(false)}>
          Mostrar menos
        </button>
      )}
    </section>
  );
}
