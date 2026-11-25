"""Discogs — estilos do lançamento (Psy-Trance, Goa Trance, Progressive Trance...).

O Discogs cataloga cada disco com `style`, uma classificação feita por gente e
mais fina que o gênero. A busca é por texto, então o primeiro resultado pode ser
outro disco: só aceitamos o que tem o título do álbum.

Precisa de token pessoal (`DISCOGS_TOKEN`); sem ele a API recusa a busca.
"""
import re
import unicodedata

import httpx

SEARCH_URL = "https://api.discogs.com/database/search"
USER_AGENT = "playlist-classifier/1.0"


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


def _titulo_do_album(titulo_discogs: str) -> str:
    # O Discogs devolve "Artista - Álbum"; o artista não entra na comparação.
    return titulo_discogs.split(" - ", 1)[-1]


def _parecido(a: str, b: str) -> bool:
    na, nb = _normalizar(a), _normalizar(b)
    if not na or not nb:
        return False
    return na in nb or nb in na


async def get_release_styles(
    client: httpx.AsyncClient, artist: str, album: str, token: str
) -> list[str] | None:
    """Estilos do lançamento que casa com o álbum.

    `[]` = achou, mas sem estilos; `None` = não achou ou a requisição falhou.
    """
    if not artist or not album or not token:
        return None
    try:
        resp = await client.get(
            SEARCH_URL,
            params={"type": "release", "artist": artist, "release_title": album, "per_page": 10},
            headers={"Authorization": f"Discogs token={token}", "User-Agent": USER_AGENT},
            timeout=10.0,
        )
        resp.raise_for_status()
        resultados = resp.json().get("results") or []
    except (httpx.HTTPError, ValueError, AttributeError):
        return None

    for item in resultados:
        if _parecido(album, _titulo_do_album(item.get("title") or "")):
            return [s for s in (item.get("style") or []) if isinstance(s, str)]
    return None
