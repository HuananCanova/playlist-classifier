import React, { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import BackLink from "../components/BackLink.jsx";
import { usePlayer } from "../PlayerContext.jsx";

function Stat({ value, label, hint }) {
  return (
    <div className="stat">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
      {hint && <span className="stat-hint">{hint}</span>}
    </div>
  );
}

/** 1234567 -> "1,2 mi"; 48210 -> "48,2 mil". Números grandes não se leem inteiros. */
function compact(n) {
  if (n == null) return null;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(".", ",")} mi`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(".", ",")} mil`;
  return String(n);
}

/**
 * Uma linha de faixa na página do artista.
 *
 * Duas origens, dois comportamentos: a faixa do acervo tem id do Spotify e
 * abre a página dela; a das mais tocadas vem do Deezer, não existe como página
 * aqui, e em troca toca a prévia no player do app.
 */
function TrackLine({ track }) {
  const { track: current, playing, playTrack } = usePlayer();

  // Id sintético: o player identifica a faixa atual por `track_id`, e as do
  // Deezer não têm id do Spotify. O prefixo evita colidir com um id real.
  const playerId = track.track_id || `deezer:${track.preview_url}`;
  const isCurrent = current?.track_id === playerId;

  const art = track.image ? (
    <img className="track-line-art" src={track.image} alt="" loading="lazy" />
  ) : (
    <span className="track-line-art track-line-art-empty" aria-hidden="true" />
  );

  const body = (
    <span className="track-line-body">
      <span className="track-line-name">{track.name}</span>
      {(track.album || track.playlist_name) && (
        <span className="track-line-sub">{track.album || track.playlist_name}</span>
      )}
    </span>
  );

  if (track.track_id) {
    return (
      <Link className="track-line" to={`/faixa/${track.track_id}`}>
        {art}
        {body}
      </Link>
    );
  }

  return (
    <div className="track-line">
      {art}
      {body}
      <span className="track-line-actions">
        {track.preview_url && (
          <button
            type="button"
            className={`btn btn-ghost btn-sm${isCurrent && playing ? " is-playing" : ""}`}
            onClick={() =>
              playTrack({
                track_id: playerId,
                name: track.name,
                artists: [],
                image: track.image,
                preview_url: track.preview_url,
              })
            }
            aria-label={`Tocar prévia de ${track.name}`}
          >
            {isCurrent && playing ? "Tocando" : "Prévia"}
          </button>
        )}
        {track.deezer_url && (
          <a
            className="btn btn-ghost btn-sm"
            href={track.deezer_url}
            target="_blank"
            rel="noreferrer"
            aria-label={`Abrir ${track.name} no Deezer`}
          >
            Deezer
          </a>
        )}
      </span>
    </div>
  );
}

export default function ArtistDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [artist, setArtist] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setArtist(null);
    setError(null);
    api
      .getArtist(id)
      .then(setArtist)
      .catch((e) =>
        setError(
          [403, 404, 429].includes(e.status) ? e.message : "Não foi possível carregar esse artista.",
        ),
      );
  }, [id]);

  if (error) {
    return (
      <div className="container">
        <BackLink onClick={() => navigate(-1)} />
        <div className="error-banner" role="alert">
          {error}
        </div>
      </div>
    );
  }

  if (!artist) {
    return (
      <div className="container">
        <BackLink onClick={() => navigate(-1)} />
        <div className="hero hero-skeleton" aria-busy="true">
          <div className="skeleton hero-art" />
          <div className="hero-body">
            <div className="skeleton skeleton-line" style={{ width: "50%", height: 30 }} />
            <div className="skeleton skeleton-line skeleton-line-short" />
          </div>
        </div>
      </div>
    );
  }

  const {
    name,
    image,
    spotify_url,
    lastfm_url,
    listeners,
    playcount,
    bio,
    tags,
    top_tracks,
    similar,
    library_tracks,
    library_track_count,
    library_playlists,
    library_scanned,
  } = artist;

  return (
    <div className="container page-enter">
        <BackLink onClick={() => navigate(-1)} />

        <section className="hero hero-artist">
          {image && (
            <div className="hero-backdrop" style={{ backgroundImage: `url(${image})` }} aria-hidden="true" />
          )}
          {image ? (
            <img className="hero-art hero-art-round" src={image} alt="" />
          ) : (
            <div className="hero-art hero-art-round hero-art-empty" aria-hidden="true" />
          )}
          <div className="hero-body">
            <p className="hero-kicker">Artista</p>
            <h1 className="hero-title">{name}</h1>

            {/* A audiência é toda do Last.fm: desde a migração de 2026 o objeto
                do artista do Spotify não traz mais seguidores nem popularidade. */}
            <div className="stat-row">
              {listeners != null && <Stat value={compact(listeners)} label="ouvintes" hint="no Last.fm" />}
              {playcount != null && (
                <Stat value={compact(playcount)} label="execuções" hint="no Last.fm" />
              )}
              {library_track_count > 0 && (
                <Stat
                  value={library_track_count}
                  label={library_track_count === 1 ? "faixa sua" : "faixas suas"}
                  hint={`em ${library_playlists.length} ${library_playlists.length === 1 ? "playlist" : "playlists"}`}
                />
              )}
            </div>

            <div className="hero-links">
              {spotify_url && (
                <a className="btn btn-ghost btn-sm" href={spotify_url} target="_blank" rel="noreferrer">
                  Abrir no Spotify
                </a>
              )}
              {lastfm_url && (
                <a className="btn btn-ghost btn-sm" href={lastfm_url} target="_blank" rel="noreferrer">
                  Abrir no Last.fm
                </a>
              )}
            </div>

            {tags.length > 0 && (
              <div className="hero-tags">
                {tags.map((t) => (
                  <span key={t} className="tag">
                    {t}
                  </span>
                ))}
              </div>
            )}
          </div>
        </section>

        {bio && (
          <section className="panel">
            <header className="panel-head">
              <h3>Quem é</h3>
              <p className="panel-sub">Biografia da comunidade do Last.fm</p>
            </header>
            <p className="artist-bio">{bio}</p>
          </section>
        )}

        <div className="charts-grid">
          <section className="panel">
            <header className="panel-head">
              <h3>Mais tocadas</h3>
              <p className="panel-sub">
                As mais ouvidas do artista no Deezer — não só as que estão nas suas playlists.
                Clique em “Prévia” para ouvir 30 segundos.
              </p>
            </header>
            {top_tracks.length > 0 ? (
              <ol className="track-lines">
                {top_tracks.map((t) => (
                  <li key={t.deezer_url || t.name}>
                    <TrackLine track={t} />
                  </li>
                ))}
              </ol>
            ) : (
              <p className="muted panel-empty">
                O Deezer não tem um artista com esse nome exato, então não há mais tocadas aqui.
              </p>
            )}
          </section>

          <section className="panel">
            <header className="panel-head">
              <h3>No seu acervo</h3>
              <p className="panel-sub">
                {library_track_count > 0
                  ? `${library_track_count} ${library_track_count === 1 ? "faixa" : "faixas"} nas playlists que você já analisou`
                  : "Faixas deste artista nas playlists que você já analisou"}
              </p>
            </header>

            {library_playlists.length > 0 && (
              <ul className="artist-playlists">
                {library_playlists.map((p) => (
                  <li key={p.id}>
                    <Link className="chip-link" to={`/playlists/${p.id}`}>
                      {p.image && <img src={p.image} alt="" loading="lazy" />}
                      {p.name}
                    </Link>
                  </li>
                ))}
              </ul>
            )}

            {library_tracks.length > 0 ? (
              <ol className="track-lines">
                {library_tracks.map((t) => (
                  <li key={`${t.playlist_id}-${t.track_id}`}>
                    <TrackLine track={t} />
                  </li>
                ))}
              </ol>
            ) : (
              <p className="muted panel-empty">
                {library_scanned
                  ? "Este artista não aparece nas playlists que você já analisou."
                  : "Nenhuma playlist analisada ainda — abra uma playlist ou monte o perfil para preencher isto."}
              </p>
            )}

            {library_track_count > library_tracks.length && (
              <p className="panel-foot muted">
                Mostrando {library_tracks.length} das {library_track_count} faixas.
              </p>
            )}
          </section>
        </div>

        {similar.length > 0 && (
          <section className="panel">
            <header className="panel-head">
              <h3>Parecidos</h3>
              <p className="panel-sub">
                Segundo o Last.fm. Quem também está no seu acervo abre aqui; o resto abre no
                Last.fm.
              </p>
            </header>
            <ul className="artist-similar">
              {similar.map((s) =>
                s.spotify_id ? (
                  <li key={s.name}>
                    <Link className="chip-link chip-link-strong" to={`/artista/${s.spotify_id}`}>
                      {s.name}
                      <span className="chip-note">no seu acervo</span>
                    </Link>
                  </li>
                ) : (
                  <li key={s.name}>
                    <a
                      className="chip-link"
                      href={s.lastfm_url || "#"}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {s.name}
                    </a>
                  </li>
                ),
              )}
            </ul>
          </section>
        )}
    </div>
  );
}
