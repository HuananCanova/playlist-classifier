import React from "react";
import { useSearchParams, Navigate } from "react-router-dom";
import { api } from "../api.js";
import { useAuth } from "../AuthContext.jsx";

export default function Login() {
  const { user, loading } = useAuth();
  const [params] = useSearchParams();
  const error = params.get("error");

  if (!loading && user) return <Navigate to="/playlists" replace />;

  return (
    <div className="center-screen fade-in">
      <div className="pulse-bars login-bars" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
      </div>
      <h1 className="login-title">
        Entenda os gêneros das suas <span className="brand-accent">playlists</span>
      </h1>
      <p className="muted login-lead">
        Conecte sua conta do Spotify para ver gráficos de gênero e subgênero de
        cada playlist, música por música.
      </p>
      {error && <div className="error-banner">Falha no login ({error}). Tente novamente.</div>}
      <a className="btn" href={api.loginUrl()}>
        Entrar com Spotify
      </a>
    </div>
  );
}
