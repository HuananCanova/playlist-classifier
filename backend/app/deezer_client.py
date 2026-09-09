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
