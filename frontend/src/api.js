const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

async function request(path, options = {}) {
  const res = await fetch(`${API_URL}${path}`, {
    credentials: "include", // send the session cookie
    ...options,
  });
  if (res.status === 401) {
    const err = new Error("unauthenticated");
    err.status = 401;
    throw err;
  }
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status}`);
  }
  return res.json();
}

export const api = {
  me: () => request("/api/auth/me"),
  logout: () => request("/api/auth/logout", { method: "POST" }),
  loginUrl: () => `${API_URL}/api/auth/login`,
  listPlaylists: () => request("/api/playlists"),
  getPlaylistAnalysis: (id) => request(`/api/playlists/${id}/analysis`),
};
