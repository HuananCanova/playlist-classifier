import React, { useEffect, useState } from "react";
import { Navigate, Route, Routes, Link, NavLink } from "react-router-dom";
import { AuthProvider, useAuth } from "./AuthContext.jsx";
import { PlayerProvider } from "./PlayerContext.jsx";
import NowPlayingBar from "./components/NowPlayingBar.jsx";
import Login from "./pages/Login.jsx";
import PlaylistList from "./pages/PlaylistList.jsx";
import PlaylistDetail from "./pages/PlaylistDetail.jsx";
import Search from "./pages/Search.jsx";
import TrackDetail from "./pages/TrackDetail.jsx";

function BrandMark() {
  return (
    <svg className="brand-mark" width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
      <defs>
        <linearGradient id="brand-grad" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="#6a55e8" />
          <stop offset="1" stopColor="#c9bfff" />
        </linearGradient>
      </defs>
      <rect width="26" height="26" rx="8" fill="url(#brand-grad)" />
      <path
        d="M6 13h1.6M9.4 9.5v7M12.8 6.5v13M16.2 9v8M19.6 11.5v3"
        stroke="#0d0b16"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

function Navbar() {
  const { user, logout } = useAuth();
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const linkClass = ({ isActive }) => `nav-link${isActive ? " nav-link-active" : ""}`;

  return (
    <header className={`navbar${scrolled ? " navbar-scrolled" : ""}`}>
      <div className="navbar-inner">
        <Link to="/" className="brand">
          <BrandMark />
          Playlist Classifier
        </Link>

        {user && (
          <nav className="nav-links" aria-label="Seções">
            <NavLink to="/playlists" className={linkClass}>
              Playlists
            </NavLink>
            <NavLink to="/busca" className={linkClass}>
              Busca
            </NavLink>
          </nav>
        )}

        {user && (
          <div className="nav-user">
            {user.image ? (
              <img className="avatar" src={user.image} alt="" />
            ) : (
              <span className="avatar avatar-fallback" aria-hidden="true">
                {(user.display_name || "?").charAt(0).toUpperCase()}
              </span>
            )}
            <span className="nav-user-name">{user.display_name}</span>
            <button className="btn btn-ghost btn-sm" onClick={logout}>
              Sair
            </button>
          </div>
        )}
      </div>
    </header>
  );
}

function RequireAuth({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="center-screen spinner-text">Carregando sua conta…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <AuthProvider>
      <PlayerProvider>
      <Navbar />
      <main>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/playlists"
            element={
              <RequireAuth>
                <PlaylistList />
              </RequireAuth>
            }
          />
          <Route
            path="/busca"
            element={
              <RequireAuth>
                <Search />
              </RequireAuth>
            }
          />
          <Route
            path="/faixa/:id"
            element={
              <RequireAuth>
                <TrackDetail />
              </RequireAuth>
            }
          />
          <Route
            path="/playlists/:id"
            element={
              <RequireAuth>
                <PlaylistDetail />
              </RequireAuth>
            }
          />
          <Route path="*" element={<Navigate to="/playlists" replace />} />
        </Routes>
      </main>
      <NowPlayingBar />
      </PlayerProvider>
    </AuthProvider>
  );
}
