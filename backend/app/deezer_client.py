"""Deezer — a fonte de BPM e do áudio de preview.

O Spotify deixou de servir para isso: `audio-features` e `audio-analysis`
respondem 403, e o campo `preview_url` sumiu do objeto de faixa nas mudanças de
2026. O Deezer tem uma API pública, sem autenticação, que devolve as duas coisas.

Duas ressalvas medidas contra a API real, que o resto do código precisa respeitar:

- **BPM existe em ~43% das faixas** (vem `0` quando desconhecido, inclusive em
  faixas mainstream). Tratamos `0` como "desconhecido", nunca como zero batidas.
- **A busca é por texto**, então pode casar com a faixa errada. Por isso cada
  resultado passa por uma verificação de similaridade antes de ser aceito.
"""
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

from .cache import deezer_cache

BASE_URL = "https://api.deezer.com"

# Diferença de duração tolerada entre a faixa do Spotify e a do Deezer. Versões
# ao vivo, remixes e edições costumam passar disso — e são justamente o que não
# queremos casar por engano.
MAX_DURATION_DIFF_S = 12


# Marcadores que descrevem a MESMA gravação — só ruído de catálogo, podem sair.
_COSMETICOS = re.compile(
    r"\s*[\(\[-]\s*[^\)\]]*\b(remaster(ed|izado)?|mono|stereo|\d{4} version)\b[^\)\]]*[\)\]]?\s*$",
    re.IGNORECASE,
)

# Marcadores que indicam uma gravação DIFERENTE. Se um lado tem e o outro não,
# não é a mesma faixa — e o BPM seria de outra performance.
_VARIANTES = re.compile(
    r"\b(ao vivo|live|remix|acoustic|acustic[ao]|unplugged|instrumental|karaoke|"
    r"radio edit|extended|demo|cover)\b",
    re.IGNORECASE,
)


def _normalizar(texto: str) -> str:
    """Minúsculas, sem acento e sem os sufixos cosméticos de catálogo."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    texto = _COSMETICOS.sub("", texto)
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


def _variantes(texto: str) -> frozenset[str]:
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return frozenset(m.group(0).lower() for m in _VARIANTES.finditer(sem_acento))


def _parecido(a: str, b: str) -> bool:
    """Um contém o outro depois de normalizar — suficiente para nomes de faixa."""
    na, nb = _normalizar(a), _normalizar(b)
    if not na or not nb:
        return False
    return na in nb or nb in na


def _confianca(candidato: dict, titulo: str, artista: str, duracao_s: int | None) -> str:
    candidato_titulo = candidato.get("title", "")

    # Ao vivo, remix e afins são outra gravação: casar um com o outro daria um
    # BPM de uma performance que não é a que o usuário tem na playlist.
    if _variantes(titulo) != _variantes(candidato_titulo):
        return "nenhuma"

    titulo_bate = _parecido(titulo, candidato_titulo)
    artista_bate = _parecido(artista, (candidato.get("artist") or {}).get("name", ""))

    if duracao_s:
        diff = abs((candidato.get("duration") or 0) - duracao_s)
        if diff > MAX_DURATION_DIFF_S:
            return "nenhuma"

    if titulo_bate and artista_bate:
        return "alta"
    if titulo_bate or artista_bate:
        return "aproximada"
    return "nenhuma"


async def buscar_faixa(
    client: httpx.AsyncClient, artista: str, titulo: str, duracao_ms: int | None = None
) -> dict | None:
    """Acha a faixa no Deezer e devolve BPM + preview, ou None se não achar.

    Devolve `confianca` junto: a interface precisa poder avisar quando a
    correspondência foi aproximada, em vez de apresentar o dado como certo.
    """
    if not artista or not titulo:
        return None

    chave = f"{_normalizar(artista)}::{_normalizar(titulo)}"
    if chave in deezer_cache:
        return deezer_cache[chave]

    duracao_s = round(duracao_ms / 1000) if duracao_ms else None

    consultas = [
        f'artist:"{artista}" track:"{titulo}"',  # busca estruturada, mais precisa
        f"{artista} {titulo}",  # texto livre, para quando a estruturada falha
    ]

    candidato = None
    confianca = "nenhuma"
    try:
        for consulta in consultas:
            resp = await client.get(f"{BASE_URL}/search", params={"q": consulta, "limit": 5})
            resp.raise_for_status()
            for item in (resp.json().get("data") or [])[:5]:
                nivel = _confianca(item, titulo, artista, duracao_s)
                if nivel == "alta":
                    candidato, confianca = item, nivel
                    break
                if nivel == "aproximada" and candidato is None:
                    candidato, confianca = item, nivel
            if confianca == "alta":
                break

        if candidato is None:
            deezer_cache[chave] = None
            return None

        # O BPM só existe no detalhe; a busca não traz.
        detalhe = await client.get(f"{BASE_URL}/track/{candidato['id']}")
        detalhe.raise_for_status()
        d = detalhe.json()
    except (httpx.HTTPError, ValueError, KeyError):
        return None  # sem cache: pode ser falha temporária de rede

    bpm = d.get("bpm")
    resultado = {
        # 0 significa "o Deezer não sabe", não "zero batidas por minuto".
        "bpm": round(bpm, 1) if isinstance(bpm, (int, float)) and bpm > 0 else None,
        "preview_url": candidato.get("preview") or None,
        "deezer_url": candidato.get("link"),
        "titulo_encontrado": candidato.get("title"),
        "artista_encontrado": (candidato.get("artist") or {}).get("name"),
        "duracao_s": candidato.get("duration"),
        "confianca": confianca,
    }
    deezer_cache[chave] = resultado
    return resultado
from . import enrichment_store
from .cache import deezer_preview_cache, deezer_track_cache

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


async def _search(client: httpx.AsyncClient, query: str) -> list[dict] | None:
    """Os candidatos, ou None se o Deezer não respondeu de verdade.

    A distinção importa porque "não achei" fica guardado por dias: o Deezer
    devolve o estouro de cota com HTTP 200 e um `error` no corpo, e tratar isso
    como lista vazia marcaria a faixa como inexistente."""
    try:
        resp = await client.get(SEARCH_URL, params={"q": query}, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(data, dict) or "error" in data:
        return None
    return data.get("data") or []


async def get_track_info(client: httpx.AsyncClient, artist: str, track: str) -> dict:
    """{'deezer_id': int|None, 'bpm': float|None, 'preview_url': str|None, 'deezer_url': str|None}.

    Nunca levanta: faixa sem correspondência no Deezer é normal, e uma análise
    de playlist inteira não pode quebrar por causa de uma música.

    A correspondência (id, BPM, link) fica guardada no banco por semanas. A
    prévia não: é uma URL assinada que expira, então quem vem do banco volta
    com `preview_url` None e a prévia é resolvida no play (`get_preview_url`).
    """
    empty = {"deezer_id": None, "bpm": None, "preview_url": None, "deezer_url": None}
    if not artist or not track:
        return empty

    cache_key = f"{artist.lower()}::{track.lower()}"
    if cache_key in deezer_track_cache:
        return deezer_track_cache[cache_key]

    stored = await asyncio.to_thread(enrichment_store.get_deezer_match, cache_key)
    if stored is not None:
        info = {**stored, "preview_url": None}
        deezer_track_cache[cache_key] = info
        return info

    # A busca vai com o título limpo: procurar "Money - 2011 Remastered Version"
    # literalmente volta vazio, porque o Deezer cataloga como "Money".
    clean_track = _strip_edition(track)

    strict = await _search(client, f'artist:"{artist}" track:"{clean_track}"')
    candidates = strict
    if not candidates:
        candidates = await _search(client, f"{artist} {clean_track}")
    if strict is None and candidates is None:
        return empty  # o Deezer não respondeu: nada a guardar

    match = _pick_best(candidates or [], artist, track)
    if not match:
        deezer_track_cache[cache_key] = empty
        await asyncio.to_thread(enrichment_store.put_deezer_match, cache_key, None, None, None)
        return empty

    info = {
        "deezer_id": match.get("id"),
        "bpm": None,
        "preview_url": match.get("preview") or None,
        "deezer_url": match.get("link") or None,
    }

    # O BPM só vem no detalhe da faixa; a busca não traz esse campo.
    detail_ok = False
    try:
        resp = await client.get(f"{TRACK_URL}/{match['id']}", timeout=10.0)
        resp.raise_for_status()
        detail = resp.json()
        if "error" not in detail:
            bpm = detail.get("bpm")
            # 0 é o "desconhecido" do Deezer — vira None para não virar "0 BPM".
            if isinstance(bpm, (int, float)) and bpm > 0:
                info["bpm"] = round(float(bpm), 1)
            info["preview_url"] = detail.get("preview") or info["preview_url"]
            info["deezer_url"] = detail.get("link") or info["deezer_url"]
            detail_ok = True
    except (httpx.HTTPError, ValueError, KeyError):
        pass  # fica só com o que a busca já deu (prévia e link)

    deezer_track_cache[cache_key] = info
    # Sem o detalhe, o BPM ficou desconhecido por falha, não por ausência:
    # guardar isso esconderia o BPM por semanas. A próxima análise tenta de novo.
    if detail_ok:
        await asyncio.to_thread(
            enrichment_store.put_deezer_match, cache_key, info["deezer_id"], info["bpm"], info["deezer_url"]
        )
    if info["preview_url"] and info["deezer_id"] is not None:
        deezer_preview_cache[info["deezer_id"]] = info["preview_url"]
    return info


async def get_preview_url(client: httpx.AsyncClient, deezer_id: int) -> str | None:
    """URL atual da prévia de 30s de uma faixa do Deezer, pelo id.

    As prévias são URLs assinadas que expiram, então não podem ser guardadas com
    a análise. Resolver na hora do play custa uma chamada (em cache por menos
    tempo que a validade da assinatura)."""
    if deezer_id in deezer_preview_cache:
        return deezer_preview_cache[deezer_id]
    try:
        resp = await client.get(f"{TRACK_URL}/{deezer_id}", timeout=10.0)
        resp.raise_for_status()
        detail = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(detail, dict) or "error" in detail:
        return None
    url = detail.get("preview") or None
    if url:
        deezer_preview_cache[deezer_id] = url
    return url


async def get_many(client: httpx.AsyncClient, pairs: list[tuple[str, str]]) -> list[dict]:
    """Busca várias faixas com a concorrência limitada pelo rate limit do Deezer."""
    semaphore = asyncio.Semaphore(DEEZER_CONCURRENCY)

    async def one(artist: str, track: str) -> dict:
        async with semaphore:
            return await get_track_info(client, artist, track)

    return await asyncio.gather(*(one(a, t) for a, t in pairs))
