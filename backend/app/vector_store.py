"""Busca semântica sobre as faixas já analisadas.

A análise de gênero conta tags exatas: ela sabe que 14 faixas têm a tag
`shoegaze`, mas não tem como responder "faixas melancólicas com guitarra",
porque nenhuma faixa carrega esse texto literal. Aqui cada faixa vira um
documento — nome, artistas, álbum e tags — embutido em um vetor, e a pergunta
vira um vetor no mesmo espaço. A proximidade entre eles é a resposta.

Decisões que valem explicar:

**Chroma embarcado, não um serviço.** O app é local-first e sem banco; subir um
Postgres com pgvector ao lado contradiria isso. O Chroma persiste em um
diretório e não pede processo nenhum.

**Embeddings locais (all-MiniLM-L6-v2, ONNX).** Rodam na CPU, sem chave de API
e sem rate limit — o que importa num projeto que já levou ban do Spotify por
volume de requisições. O modelo baixa uma vez (~80 MB) e fica em cache.

**Um documento por faixa, não por par (playlist, faixa).** A mesma música em
três playlists deve aparecer uma vez na busca global. O recorte por playlist,
quando é preciso, vem de um filtro `$in` sobre os ids — a análise da playlist
já está em cache, então a lista sai de graça.

**O corpus é o que você já olhou.** Indexar acontece como efeito colateral da
análise de uma playlist, com os dados que já foram buscados. Nenhuma chamada
externa a mais: o índice cresce conforme você navega, e nunca sozinho.
"""
import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Ao lado do backend, fora do controle de versão (ver .gitignore).
CHROMA_PATH = Path(__file__).resolve().parent.parent / ".chroma"
COLLECTION = "faixas"

# Carregar o modelo ONNX leva alguns segundos; só acontece no primeiro uso, e
# não no import, para não atrasar o boot do FastAPI.
_collection: Any = None
_lock = asyncio.Lock()


def _build_collection() -> Any:
    import chromadb
    from chromadb.utils import embedding_functions

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return client.get_or_create_collection(
        name=COLLECTION,
        embedding_function=embedding_functions.DefaultEmbeddingFunction(),
        # Cosseno, não L2: documentos de tags variam muito de comprimento
        # (uma faixa obscura tem 2 tags, uma popular tem 40) e a distância
        # euclidiana leria esse comprimento como diferença de conteúdo.
        metadata={"hnsw:space": "cosine"},
    )


async def _get_collection() -> Any:
    global _collection
    if _collection is None:
        async with _lock:
            if _collection is None:
                _collection = await asyncio.to_thread(_build_collection)
                logger.info("Índice vetorial pronto em %s", CHROMA_PATH)
    return _collection


def _documento(nome: str, artistas: list[str], album: str | None, tags: list[str]) -> str:
    """Texto que representa a faixa no espaço vetorial.

    As tags entram por último e sem repetição: são o sinal mais forte de estilo,
    e duplicá-las só enviesaria o vetor para o que já está representado.
    """
    partes = [nome]
    if artistas:
        partes.append(" — " + ", ".join(artistas))
    if album:
        partes.append(f". Álbum: {album}")
    if tags:
        vistos = list(dict.fromkeys(t.strip().lower() for t in tags if t and t.strip()))
        partes.append(". Tags: " + ", ".join(vistos))
    return "".join(partes)


async def index_tracks(tracks: list[dict]) -> int:
    """Indexa (ou reindexa) faixas. Cada dict traz track_id, nome, artistas, album, tags.

    Usa `upsert`: reanalisar a mesma playlist atualiza os documentos em vez de
    duplicá-los, e uma faixa que ganhou tags novas no Last.fm reflete isso.
    """
    uteis = [t for t in tracks if t.get("track_id")]
    if not uteis:
        return 0

    col = await _get_collection()
    ids = [t["track_id"] for t in uteis]
    documentos = [
        _documento(
            t.get("nome") or "",
            t.get("artistas") or [],
            t.get("album"),
            t.get("tags") or [],
        )
        for t in uteis
    ]
    metadados = [
        {
            "nome": t.get("nome") or "",
            # Chroma só guarda escalares nos metadados, então a lista vira texto.
            "artistas": ", ".join(t.get("artistas") or []),
            "album": t.get("album") or "",
            "tags": ", ".join((t.get("tags") or [])[:12]),
        }
        for t in uteis
    ]

    await asyncio.to_thread(col.upsert, ids=ids, documents=documentos, metadatas=metadados)
    logger.info("Indexadas %d faixas", len(ids))
    return len(ids)


def _formatar(resultado: dict, pular: str | None = None) -> list[dict]:
    ids = (resultado.get("ids") or [[]])[0]
    metadados = (resultado.get("metadatas") or [[]])[0]
    distancias = (resultado.get("distances") or [[]])[0]

    saida = []
    for track_id, meta, distancia in zip(ids, metadados, distancias):
        if pular is not None and track_id == pular:
            continue
        meta = meta or {}
        saida.append(
            {
                "track_id": track_id,
                "nome": meta.get("nome") or "",
                "artistas": [a for a in (meta.get("artistas") or "").split(", ") if a],
                "album": meta.get("album") or None,
                "tags": [t for t in (meta.get("tags") or "").split(", ") if t],
                # Distância cosseno vai de 0 (idêntico) a 2. Similaridade é mais
                # legível para quem consome a API — e para o modelo no chat.
                "similaridade": round(1 - float(distancia), 4),
            }
        )
    return saida


async def search(consulta: str, limite: int = 20, track_ids: list[str] | None = None) -> list[dict]:
    """Busca semântica. `track_ids` restringe a busca a um subconjunto (uma playlist)."""
    if not consulta.strip():
        return []

    col = await _get_collection()
    if await asyncio.to_thread(col.count) == 0:
        return []

    # O recorte por playlist vai em `ids`, não em `where`: `where` filtra
    # metadados, e a playlist não é um deles — uma faixa pertence a várias.
    kwargs: dict = {"query_texts": [consulta], "n_results": limite}
    if track_ids:
        kwargs["ids"] = track_ids

    resultado = await asyncio.to_thread(col.query, **kwargs)
    return _formatar(resultado)


async def similar_to_track(track_id: str, limite: int = 10) -> list[dict]:
    """Vizinhos mais próximos de uma faixa já indexada.

    Consulta pelo embedding que já está guardado, em vez de reembutir o texto:
    é o mesmo vetor e evita rodar o modelo à toa.
    """
    col = await _get_collection()
    existente = await asyncio.to_thread(col.get, ids=[track_id], include=["embeddings"])
    embeddings = existente.get("embeddings")
    if embeddings is None or len(embeddings) == 0:
        return []

    resultado = await asyncio.to_thread(
        col.query,
        query_embeddings=[embeddings[0]],
        # Um a mais: a própria faixa volta como o vizinho mais próximo dela mesma.
        n_results=limite + 1,
    )
    return _formatar(resultado, pular=track_id)[:limite]


async def stats() -> dict:
    col = await _get_collection()
    total = await asyncio.to_thread(col.count)
    return {"faixas_indexadas": total, "caminho": str(CHROMA_PATH)}
