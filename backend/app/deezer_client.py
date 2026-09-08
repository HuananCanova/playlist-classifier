"""Buscas na API pública do Deezer — BPM e prévia de 30s por faixa.

Por que Deezer: desde 27/11/2024 o Spotify cortou `/audio-features` (de onde
vinha o BPM) e o `preview_url` para apps novos. Este app cai nessa regra — os
dois voltam 403/None. O Deezer expõe as duas coisas sem chave nenhuma.

Duas ressalvas que moldam este módulo:

1. `bpm: 0` no Deezer quer dizer "não sei", não "zero batidas". Tratar 0 como
   valor real encheria a tabela de faixas com "0 BPM".
2. A busca por campos (`artist:"x" track:"y"`) é precisa mas perde muito
   (não acha "Daft Punk / Get Lucky", por exemplo). A busca livre acha quase
   sempre, mas devolve covers, remixes e karaokê. Então: tenta a estrita,
   cai pra livre, e valida o candidato comparando título e artista
   normalizados — senão o BPM exibido seria de outra gravação.
"""
import asyncio
import re
import unicodedata

import httpx

from .cache import deezer_track_cache

SEARCH_URL = "https://api.deezer.com/search"
TRACK_URL = "https://api.deezer.com/track"

# O Deezer limita ~50 requisições a cada 5s por IP. Cada faixa custa até duas
# (busca + detalhe), então 6 em paralelo deixa folga sem arrastar a análise.
DEEZER_CONCURRENCY = 6

# Abaixo disso o candidato é considerado outra gravação e descartado.
MIN_TITLE_SCORE = 0.62

# Sufixos que o Spotify carrega e o Deezer normalmente não ("- 2011 Remastered
# Version", "(feat. X)"). Comparar com eles derrubaria o score de faixas que na
# verdade batem, e procurar por eles faz a busca voltar vazia.
_EDITION_WORDS = (
    r"remaster(?:ed)?|ao vivo|live|radio edit|single version|album version|"
    r"bonus track|deluxe|mono|stereo|edit|version|vers[aã]o"
)
_NOISE_PATTERNS = [
    r"\((?:feat|ft)\.?[^)]*\)", r"\[(?:feat|ft)\.?[^\]]*\]",
    r"\b(?:feat|ft)\.?\s.*$",
    rf"\([^)]*(?:{_EDITION_WORDS})[^)]*\)",
    # O ano costuma vir no meio ("- 2011 Remastered Version"), então qualquer
    # coisa entre o traço e a palavra de edição também cai.
    rf"-\s*[^-]*(?:{_EDITION_WORDS})\b.*$",
]


def _strip_edition(text: str) -> str:
    """Tira os sufixos de edição mantendo acentos e maiúsculas — o que vai na
    query. (`_normalize` é mais agressivo e serve só para comparar.)"""
    for pattern in _NOISE_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip() or text


def _normalize(text: str) -> str:
    """Minúsculas, sem acento, sem pontuação e sem os sufixos de edição."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    for pattern in _NOISE_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _similarity(a: str, b: str) -> float:
    """Sobreposição de palavras (Jaccard). Barato e suficiente aqui: os títulos
    já chegam normalizados, então o que resta é ordem e palavras extras."""
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _pick_best(candidates: list[dict], artist: str, track: str) -> dict | None:
    """Melhor candidato acima do limiar, priorizando quem também bate o artista."""
    want_track, want_artist = _normalize(track), _normalize(artist)
    best, best_score = None, 0.0

    for cand in candidates:
        title_score = _similarity(_normalize(cand.get("title", "")), want_track)
        if title_score < MIN_TITLE_SCORE:
            continue
        cand_artist = _normalize((cand.get("artist") or {}).get("name", ""))
        # O artista desempata mas não elimina: colaborações e grafias
        # diferentes são comuns, e o título já filtrou o grosso.
        score = title_score + 0.5 * _similarity(cand_artist, want_artist)
        if score > best_score:
            best, best_score = cand, score

    return best


async def _search(client: httpx.AsyncClient, query: str) -> list[dict]:
    try:
        resp = await client.get(SEARCH_URL, params={"q": query}, timeout=10.0)
        resp.raise_for_status()
        return resp.json().get("data", []) or []
    except (httpx.HTTPError, ValueError):
        return []


async def get_track_info(client: httpx.AsyncClient, artist: str, track: str) -> dict:
    """{'bpm': float|None, 'preview_url': str|None, 'deezer_url': str|None}.

    Nunca levanta: faixa sem correspondência no Deezer é normal, e uma análise
    de playlist inteira não pode quebrar por causa de uma música.
    """
    empty = {"bpm": None, "preview_url": None, "deezer_url": None}
    if not artist or not track:
        return empty

    cache_key = f"{artist.lower()}::{track.lower()}"
    if cache_key in deezer_track_cache:
        return deezer_track_cache[cache_key]

    # A busca vai com o título limpo: procurar "Money - 2011 Remastered Version"
    # literalmente volta vazio, porque o Deezer cataloga como "Money".
    clean_track = _strip_edition(track)

    candidates = await _search(client, f'artist:"{artist}" track:"{clean_track}"')
    if not candidates:
        candidates = await _search(client, f"{artist} {clean_track}")

    match = _pick_best(candidates, artist, track)
    if not match:
        deezer_track_cache[cache_key] = empty
        return empty

    info = {
        "bpm": None,
        "preview_url": match.get("preview") or None,
        "deezer_url": match.get("link") or None,
    }

    # O BPM só vem no detalhe da faixa; a busca não traz esse campo.
    try:
        resp = await client.get(f"{TRACK_URL}/{match['id']}", timeout=10.0)
        resp.raise_for_status()
        detail = resp.json()
        bpm = detail.get("bpm")
        # 0 é o "desconhecido" do Deezer — vira None para não virar "0 BPM".
        if isinstance(bpm, (int, float)) and bpm > 0:
            info["bpm"] = round(float(bpm), 1)
        info["preview_url"] = detail.get("preview") or info["preview_url"]
        info["deezer_url"] = detail.get("link") or info["deezer_url"]
    except (httpx.HTTPError, ValueError, KeyError):
        pass  # fica só com o que a busca já deu (prévia e link)

    deezer_track_cache[cache_key] = info
    return info


async def get_many(client: httpx.AsyncClient, pairs: list[tuple[str, str]]) -> list[dict]:
    """Busca várias faixas com a concorrência limitada pelo rate limit do Deezer."""
    semaphore = asyncio.Semaphore(DEEZER_CONCURRENCY)

    async def one(artist: str, track: str) -> dict:
        async with semaphore:
            return await get_track_info(client, artist, track)

    return await asyncio.gather(*(one(a, t) for a, t in pairs))
