import React, { createContext, useContext, useEffect, useState } from "react";
import { api } from "./api.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    try {
      const me = await api.me();
      setUser(me);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  // Assim que há sessão, pede ao backend que indexe as playlists que ainda
  // faltam. É fire-and-forget de propósito: o índice é enriquecimento, e uma
  // falha aqui não pode atrapalhar quem só quer ver as playlists. O backend
  // decide se realmente roda — ele respeita AUTO_INDEX e ignora o pedido se
  // já houver varredura em andamento.
  useEffect(() => {
    if (!user) return;
    api.startIndex({ auto: true }).catch(() => {});
  }, [user?.id]);

  const logout = async () => {
    await api.logout();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
