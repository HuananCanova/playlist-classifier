"""Obtém, uma única vez, o refresh token que o servidor MCP usa.

O app web guarda os tokens no cookie de sessão, que só existe dentro do
navegador. O servidor MCP roda como um processo solto, iniciado pelo cliente
MCP — sem navegador e sem cookie. Este script faz o mesmo fluxo OAuth (code +
PKCE) na linha de comando e imprime o refresh token para você colar no `.env`.

Reaproveita o `SPOTIFY_REDIRECT_URI` que já está registrado no painel do
Spotify, então **o backend precisa estar parado** enquanto isso roda: os dois
disputariam a mesma porta.

Uso:
    cd backend
    python -m scripts.spotify_refresh_token
"""
import base64
import hashlib
import http.server
import secrets
import sys
import threading
import urllib.parse
import webbrowser

import httpx

from app.config import get_settings
from app.spotify_auth import SPOTIFY_AUTHORIZE_URL, SPOTIFY_TOKEN_URL

# Preenchido pelo handler quando o Spotify redireciona de volta.
_resultado: dict[str, str] = {}
_pronto = threading.Event()


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (nome exigido pela BaseHTTPRequestHandler)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _resultado.update({k: v[0] for k, v in query.items()})

        ok = "code" in _resultado
        corpo = (
            "<h2>Pronto.</h2><p>Pode fechar esta aba e voltar ao terminal.</p>"
            if ok
            else f"<h2>Falhou.</h2><p>{_resultado.get('error', 'sem código')}</p>"
        )
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(corpo.encode("utf-8"))
        _pronto.set()

    def log_message(self, *args) -> None:
        """Silencia o log de acesso — o script já imprime o que importa."""


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def main() -> int:
    settings = get_settings()
    redirect = urllib.parse.urlparse(settings.spotify_redirect_uri)
    host, porta = redirect.hostname or "127.0.0.1", redirect.port or 80

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": settings.spotify_client_id,
        "response_type": "code",
        "redirect_uri": settings.spotify_redirect_uri,
        "state": state,
        "scope": settings.spotify_scopes,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    url = f"{SPOTIFY_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    try:
        servidor = http.server.HTTPServer((host, porta), _CallbackHandler)
    except OSError as exc:
        print(f"Não consegui abrir {host}:{porta} — {exc}", file=sys.stderr)
        print("O backend provavelmente está rodando. Pare-o e tente de novo.", file=sys.stderr)
        return 1

    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    print(f"Abrindo o navegador para autorizar…\nSe não abrir, acesse:\n{url}\n")
    webbrowser.open(url)

    if not _pronto.wait(timeout=300):
        print("Tempo esgotado esperando a autorização.", file=sys.stderr)
        return 1
    servidor.shutdown()

    if _resultado.get("state") != state:
        print("O `state` de volta não confere — autorização descartada.", file=sys.stderr)
        return 1
    if "code" not in _resultado:
        print(f"O Spotify recusou: {_resultado.get('error')}", file=sys.stderr)
        return 1

    resp = httpx.post(
        SPOTIFY_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": _resultado["code"],
            "redirect_uri": settings.spotify_redirect_uri,
            "client_id": settings.spotify_client_id,
            "code_verifier": verifier,
        },
        auth=(settings.spotify_client_id, settings.spotify_client_secret),
        timeout=20.0,
    )
    if resp.status_code != 200:
        print(f"Troca do código falhou (HTTP {resp.status_code}): {resp.text}", file=sys.stderr)
        return 1

    refresh = resp.json().get("refresh_token")
    if not refresh:
        print("O Spotify não devolveu refresh_token.", file=sys.stderr)
        return 1

    print("\nCole esta linha no backend/.env:\n")
    print(f"SPOTIFY_REFRESH_TOKEN={refresh}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
