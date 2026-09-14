import React from "react";
import { useSearchParams, Navigate } from "react-router-dom";
import { api } from "../api.js";
import { useAuth } from "../AuthContext.jsx";
import SoundRibbon from "../components/SoundRibbon.jsx";

const LOGIN_ERRORS = {
  access_denied: "Você recusou o acesso no Spotify. Entre de novo e autorize para continuar.",
  invalid_state: "O login expirou no meio do caminho. Entre de novo.",
  token_exchange_failed: "O Spotify não confirmou o login. Entre de novo.",
};

export default function Login() {
  const { user, loading } = useAuth();
  const [params] = useSearchParams();
  const error = params.get("error");

  if (!loading && user) return <Navigate to="/playlists" replace />;

  return (
    <div className="landing">
      <div className="landing-copy">
        <h1 className="landing-title">Do que suas playlists são feitas</h1>
        <p className="landing-lead">
          Conecte o Spotify e veja cada playlist desmontada em gêneros, subgêneros e
          andamento, faixa por faixa.
        </p>
        {error && (
          <p className="error-banner landing-error" role="alert">
            {LOGIN_ERRORS[error] || `O login falhou (${error}). Entre de novo.`}
          </p>
        )}
        <a className="btn btn-light btn-lg" href={api.loginUrl()}>
          <SpotifyGlyph />
          Entrar com Spotify
        </a>
      </div>

      <div className="landing-stage">
        <SoundRibbon className="landing-ribbon" lines={34} />

        {/* Ilustram o que a análise mostra; o rótulo deixa claro que é um exemplo. */}
        <figure className="float-card float-card-left" aria-hidden="true">
          <figcaption>Exemplo de gênero dominante</figcaption>
          <strong>indie rock</strong>
          <span className="float-meter">
            <span style={{ width: "42%" }} />
          </span>
          <span className="float-note">42% das faixas</span>
        </figure>
        <figure className="float-card float-card-right" aria-hidden="true">
          <figcaption>Exemplo de andamento</figcaption>
          <strong className="float-figure">118</strong>
          <span className="float-note">BPM médio, zona dançante</span>
        </figure>
      </div>
    </div>
  );
}

function SpotifyGlyph() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="11" fill="#1db954" />
      <path
        d="M6.6 9.4c3.7-1.1 7.9-.8 11 1M7.2 12.6c3-.9 6.4-.6 8.9.8M7.8 15.6c2.4-.6 4.9-.4 6.9.7"
        stroke="#0a0a0a"
        strokeWidth="1.6"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}
