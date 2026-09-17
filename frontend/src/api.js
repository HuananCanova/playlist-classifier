const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

// Requisições GET idênticas ainda em voo, por caminho.
//
// O StrictMode dispara cada efeito duas vezes em desenvolvimento, então toda
// tela fazia duas chamadas iguais — e cada abertura de playlist custa várias
// chamadas ao Spotify, que tem rate limit severo. Voltar a mesma promessa
// resolve na origem, sem desligar o StrictMode (que existe justamente para
// expor efeitos não idempotentes).
const inFlight = new Map();

function dedupe(key, run) {
  const existing = inFlight.get(key);
  if (existing) return existing;

  const promise = run().finally(() => inFlight.delete(key));
  inFlight.set(key, promise);
  return promise;
}

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
    // O backend manda uma explicação em `detail` (limite do Spotify, playlist
    // inexistente...). Sem repassar isso, toda falha vira a mesma frase genérica.
    let detail = null;
    try {
      detail = (await res.json())?.detail;
    } catch {
      // resposta sem corpo JSON — segue com a mensagem padrão
    }
    const err = new Error(detail || `Request failed: ${res.status}`);
    err.status = res.status;
    err.retryAfter = Number(res.headers.get("Retry-After")) || null;
    throw err;
  }
  return res.json();
}

// Só os GETs entram no dedupe: logout é uma ação, e reaproveitar a promessa de
// uma ação em andamento esconderia um segundo clique de propósito diferente.
const get = (path) => dedupe(path, () => request(path));

/** "~18 h" / "~5 min" / "~40 s" — para o Retry-After que um humano vai ler. */
export function formatWait(seconds) {
  if (!seconds) return "";
  if (seconds >= 5400) return `~${Math.round(seconds / 3600)} h`;
  if (seconds >= 90) return `~${Math.round(seconds / 60)} min`;
  return `~${Math.round(seconds)} s`;
}

export const api = {
  me: () => get("/api/auth/me"),
  logout: () => request("/api/auth/logout", { method: "POST" }),
  loginUrl: () => `${API_URL}/api/auth/login`,
  listPlaylists: ({ refresh = false } = {}) =>
    get(`/api/playlists${refresh ? "?refresh=true" : ""}`),
  getPlaylistAnalysis: (id) => get(`/api/playlists/${id}/analysis`),
  getTrack: (id) => request(`/api/tracks/${id}`),
  // A prévia expira em minutos, então não vem guardada com a análise.
  getPreview: (deezerId) => get(`/api/tracks/preview/${deezerId}`),
  getSimilarTracks: (id, limit = 8) =>
    request(`/api/tracks/${id}/similar?limit=${limit}`),
  search: (q, limit = 20) =>
    request(`/api/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  searchStatus: () => request("/api/search/status"),
  indexStatus: () => request("/api/search/index"),
  startIndex: ({ auto = false } = {}) =>
    request(`/api/search/index?auto=${auto}`, { method: "POST" }),
  stopIndex: () => request("/api/search/index", { method: "DELETE" }),
  getPlaylistClusters: (id) => request(`/api/playlists/${id}/clusters`),
  chatStatus: () => get("/api/chat/status"),
  getProfile: () => get("/api/profile"),
  getProfileBuild: () => get("/api/profile/build"),
  buildProfile: () => request("/api/profile/build", { method: "POST" }),

  // Não passa por request(): precisamos do corpo como stream, não como JSON.
  chatStream: async (messages, { playlistId = null, trackId = null } = {}) => {
    const body = { messages };
    if (playlistId) body.playlist_id = playlistId;
    if (trackId) body.track_id = trackId;

    const res = await fetch(`${API_URL}/api/chat`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`Chat failed: ${res.status}`);
    return res;
  },
};
