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

export const api = {
  me: () => get("/api/auth/me"),
  logout: () => request("/api/auth/logout", { method: "POST" }),
  loginUrl: () => `${API_URL}/api/auth/login`,
  listPlaylists: ({ refresh = false } = {}) =>
    get(`/api/playlists${refresh ? "?refresh=true" : ""}`),
  getPlaylistAnalysis: (id) => get(`/api/playlists/${id}/analysis`),
  chatStatus: () => get("/api/chat/status"),

  // Não passa por request(): precisamos do corpo como stream, não como JSON.
  chatStream: async (messages, playlistId = null) => {
    const res = await fetch(`${API_URL}/api/chat`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(playlistId ? { messages, playlist_id: playlistId } : { messages }),
    });
    if (!res.ok) throw new Error(`Chat failed: ${res.status}`);
    return res;
  },
};
