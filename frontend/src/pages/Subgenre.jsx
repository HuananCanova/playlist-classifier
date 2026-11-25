import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api.js";
import BackLink from "../components/BackLink.jsx";
import EnrichPanel from "../components/EnrichPanel.jsx";
import { PauseIcon, PlayIcon } from "../components/TrackTable.jsx";
import { usePlayer } from "../PlayerContext.jsx";

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

export default function Subgenre() {
  const params = useParams();
  let name = params.name ?? "";
  try {
    name = decodeURIComponent(name);
  } catch {
    // nome malformado: usa como veio e deixa a API dizer que não existe
  }

  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const next = await api.getSubgenre(name);
      if (mine !== seq.current) return;
      setData(next);
      setError(null);
    } catch (e) {
      if (mine !== seq.current) return;
      setError({ status: e.status, message: e.message || "Não foi possível carregar o subgênero." });
    }
  }, [name]);

  useEffect(() => {
    setData(null);
    setError(null);
    load();
    return () => {
      seq.current++;
    };
  }, [load]);

  if (error?.status === 404) {
    return (
      <div className="container">
        <BackLink to="/perfil" />
        <div className="empty-state">
          <h2>Subgênero desconhecido</h2>
          <p>
            Não existe um subgênero chamado “{name}”. <Link to="/perfil">Voltar ao perfil</Link>
          </p>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="container">
        <BackLink to="/perfil" />
        <div className="error-banner" role="alert">
          <span>{error.message}</span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={load}>
            Tentar de novo
          </button>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="container" aria-busy="true">
        <BackLink to="/perfil" />
        <h1 className="hero-title">{name}</h1>
        <p className="spinner-text">Carregando…</p>
      </div>
    );
  }

  const info = data.info ?? {};
  const confident = data.confident ?? [];
  const leaning = data.leaning ?? [];
  const host = info.source ? hostOf(info.source) : null;
  const bpm = Array.isArray(info.bpm) ? info.bpm : null;
  const title = info.name || name;

  return (
    <div className="container page-enter">
      <BackLink to="/perfil" />
      <header className="section-head">
        {info.genre && <p className="profile-kicker">{info.genre}</p>}
        <h1 className="hero-title">{title}</h1>
        {info.about && <p className="panel-sub">{info.about}</p>}
        {bpm && (
          <p className="panel-sub">
            BPM: {bpm[0]}–{bpm[1]}
            {host && (
              <>
                {" · segundo "}
                <a href={info.source} target="_blank" rel="noopener noreferrer">
                  {host}
                </a>
              </>
            )}
          </p>
        )}
      </header>

      <EnrichPanel onDone={load} />

      <TrackSection
        title={`Classificadas como ${title}`}
        tracks={confident}
        name={title}
        empty="Nenhuma faixa classificada com segurança neste subgênero ainda."
      />
      <TrackSection
        title={`Tendem a ${title} (incertas)`}
        tracks={leaning}
        name={title}
        empty="Nenhuma faixa incerta puxa para este subgênero."
      />
    </div>
  );
}

function TrackSection({ title, tracks, name, empty }) {
  return (
    <section className="panel">
      <header className="panel-head">
        <h3>
          {title} <span className="muted">({tracks.length})</span>
        </h3>
      </header>
      {tracks.length === 0 ? (
        <p className="muted">{empty}</p>
      ) : (
        <ol className="cut-list">
          {tracks.map((t) => (
            <li key={t.id}>
              <TrackRow track={t} name={name} />
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function TrackRow({ track: t, name }) {
  const share = typeof t.share === "number" ? Math.round(t.share * 100) : null;
  const playlists = t.playlists ?? [];
  const { track: current, playing, playTrack } = usePlayer();
  const isCurrent = current?.track_id === t.id;
  return (
    <div className="cut-row">
      {t.deezer_id ? (
        <button
          type="button"
          className="play-btn"
          onClick={() => playTrack({ track_id: t.id, name: t.name, artists: t.artists, image: t.image, deezer_id: t.deezer_id })}
          aria-label={isCurrent && playing ? `Pausar ${t.name}` : `Tocar prévia de ${t.name}`}
        >
          {isCurrent && playing ? <PauseIcon size={12} /> : <PlayIcon size={12} />}
        </button>
      ) : null}
      {t.image ? <img src={t.image} alt="" loading="lazy" /> : <span className="cut-art-empty" aria-hidden="true" />}
      <span className="cut-text">
        <Link to={`/faixa/${t.id}`} className="cut-name">
          {t.name || "Faixa sem nome"}
        </Link>
        <span className="cut-sub">
          {(t.artists ?? []).join(", ")}
          {share != null && (
            <span className="cut-genre">
              {share}% {name}
            </span>
          )}
          {t.bpm != null && <span className="cut-genre">{Math.round(t.bpm)} BPM</span>}
        </span>
        {playlists.length > 0 && (
          <span className="cut-sub">
            {playlists.map((p) => (
              <Link key={p.id} to={`/playlists/${p.id}`} className="tag">
                {p.name}
              </Link>
            ))}
          </span>
        )}
      </span>
    </div>
  );
}
