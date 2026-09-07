import React, { useEffect, useState } from "react";
import { Navigate, Route, Routes, Link, NavLink } from "react-router-dom";
import { AuthProvider, useAuth } from "./AuthContext.jsx";
import Login from "./pages/Login.jsx";
import PlaylistList from "./pages/PlaylistList.jsx";
import PlaylistDetail from "./pages/PlaylistDetail.jsx";

function Navbar() {
  const { user, logout } = useAuth();
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header className={`navbar${scrolled ? " navbar-scrolled" : ""}`}>
      <div className="navbar-inner">
        <Link to="/" className="brand">
          <span className="brand-mark" aria-hidden="true" />
          Playlist<span className="brand-accent">Classifier</span>
        </Link>

        {user && (
          <nav className="nav-links">
            <NavLink
              to="/playlists"
              className={({ isActive }) => `nav-link${isActive ? " nav-link-active" : ""}`}
            >
              Playlists
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
            <button className="btn btn-secondary btn-sm" onClick={logout}>
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
  if (loading) return <div className="center-screen spinner-text">Carregando…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <AuthProvider>
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
    </AuthProvider>
  );
}
