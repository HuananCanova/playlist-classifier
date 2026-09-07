"""As ferramentas do agente — independentes de provedor.

Aqui mora a lógica: o que o agente consegue buscar e com que teto de tamanho.
Os adaptadores (`ai_chat.py` para Claude, `ai_chat_groq.py` para Groq) apenas
traduzem estas funções para o formato de cada API.

Para adicionar busca ou recomendação, escreva a função e registre em
`build_tools()` — os dois provedores ganham a capacidade de uma vez.
"""
import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from .genre_analysis import build_playlist_analysis
from .spotify_client import SpotifyClient

# Quantos itens cada ferramenta devolve no máximo. Uma playlist de 500 faixas
# viraria dezenas de milhares de tokens por chamada sem esses tetos.
MAX_PLAYLISTS = 60
MAX_TRACK_SAMPLE = 40
MAX_GENRES = 15
# Teto de playlists numa visão geral: cada uma custa segundos, mesmo em paralelo.
MAX_OVERVIEW = 12


@dataclass(frozen=True)
class Tool:
    """Uma ferramenta, no formato neutro que os dois adaptadores consomem."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema dos argumentos
    run: Callable[..., Awaitable[str]]


def build_tools(access_token: str, playlist_id: str | None = None) -> list[Tool]:
    """Cria as ferramentas ligadas à sessão do usuário.

    O token do Spotify fica capturado no closure, não como parâmetro de
    ferramenta: o modelo nem vê a credencial nem consegue passá-la errada.

    Com `playlist_id`, devolve só a ferramenta daquela playlist — o chat da
    página de detalhe não deve poder listar nem analisar as outras.
    """

    async def listar_playlists() -> str:
        spotify = SpotifyClient(access_token)
        async with httpx.AsyncClient(timeout=20.0) as client:
            raw = await spotify.get_all_playlists(client)

        items = []
        for p in raw[:MAX_PLAYLISTS]:
            if not p:
                continue
            total = (p.get("items") or p.get("tracks") or {}).get("total", 0)
            items.append({"id": p.get("id"), "nome": p.get("name"), "faixas": total})

        return json.dumps(
            {"total_de_playlists": len(raw), "playlists": items}, ensure_ascii=False
        )

    async def analisar_playlist(playlist_id: str) -> str:
        try:
            analysis = await build_playlist_analysis(access_token, playlist_id)
        except httpx.HTTPStatusError as exc:
            # Devolvido como resultado, não levantado: assim o modelo explica o
            # problema ao usuário em vez de a conversa inteira morrer.
            return json.dumps(
                {
                    "erro": "Não consegui ler essa playlist no Spotify "
                    f"(HTTP {exc.response.status_code})."
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "playlist": analysis.playlist.name,
                "total_de_faixas": analysis.playlist.track_count,
                "faixas_sem_genero": analysis.tracks_missing_genre,
                "generos": [
                    {"genero": g.label, "faixas": g.count}
                    for g in analysis.genre_distribution[:MAX_GENRES]
                ],
                "subgeneros": [
                    {"tag": g.label, "faixas": g.count}
                    for g in analysis.subgenre_distribution[:MAX_GENRES]
                ],
                "artistas_frequentes": [
                    {"artista": a.label, "faixas": a.count}
                    for a in analysis.top_artists[:10]
                ],
                "amostra_de_faixas": [
                    {"faixa": t.name, "artistas": t.artists, "tags": t.subgenre_tags[:4]}
                    for t in analysis.tracks[:MAX_TRACK_SAMPLE]
                ],
                "observacao": (
                    f"A amostra mostra {min(MAX_TRACK_SAMPLE, len(analysis.tracks))} "
                    f"de {len(analysis.tracks)} faixas."
                ),
            },
            ensure_ascii=False,
        )

    def _track_total(p: dict) -> int:
        return (p.get("items") or p.get("tracks") or {}).get("total", 0) or 0

    async def visao_geral(limite: int = 6) -> str:
        spotify = SpotifyClient(access_token)
        async with httpx.AsyncClient(timeout=20.0) as client:
            raw = await spotify.get_all_playlists(client)

        # As maiores primeiro: numa conta com dezenas de playlists, as primeiras
        # da lista são uma amostra arbitrária, enquanto as maiores concentram a
        # maior parte das faixas — e portanto do sinal sobre o gosto.
        candidatas = sorted(
            (p for p in raw if p and p.get("id")), key=_track_total, reverse=True
        )
        alvo = candidatas[: max(1, min(limite, MAX_OVERVIEW))]

        async def resumir(p: dict) -> dict:
            try:
                a = await build_playlist_analysis(access_token, p["id"])
            except Exception:
                # Uma playlist ilegível não pode derrubar a visão geral inteira.
                return {"playlist": p.get("name"), "erro": "não foi possível analisar"}
            return {
                "playlist": a.playlist.name,
                "faixas": a.playlist.track_count,
                "generos": [
                    {"genero": g.label, "faixas": g.count}
                    for g in a.genre_distribution[:5]
                ],
            }

        # O fan-out caro fica aqui, em paralelo: o modelo gasta um turno só, em
        # vez de um turno por playlist.
        resumos = await asyncio.gather(*(resumir(p) for p in alvo))

        # Agregado da coleção, que é o que perguntas amplas realmente querem.
        totais: dict[str, int] = {}
        for r in resumos:
            for g in r.get("generos", []):
                totais[g["genero"]] = totais.get(g["genero"], 0) + g["faixas"]
        ranking = sorted(totais.items(), key=lambda kv: kv[1], reverse=True)[:MAX_GENRES]

        faixas_analisadas = sum(r.get("faixas", 0) for r in resumos)
        faixas_totais = sum(_track_total(p) for p in raw)
        cobertura = round(100 * faixas_analisadas / faixas_totais) if faixas_totais else 0

        return json.dumps(
            {
                "playlists_analisadas": len(resumos),
                "total_de_playlists_na_conta": len(raw),
                "faixas_analisadas": faixas_analisadas,
                "faixas_na_conta": faixas_totais,
                "cobertura_percentual": cobertura,
                "generos_somados": [{"genero": g, "faixas": n} for g, n in ranking],
                "por_playlist": resumos,
                "observacao": (
                    f"Amostra: as {len(resumos)} maiores playlists de {len(raw)}, "
                    f"cobrindo {faixas_analisadas} de {faixas_totais} faixas "
                    f"(~{cobertura}% da conta). Diga isso ao usuário: com uma conta "
                    "grande, a amostra pode não representar toda a coleção. Se ele "
                    "quiser mais abrangência, ofereça repetir com um `limite` maior "
                    f"(até {MAX_OVERVIEW})."
                ),
            },
            ensure_ascii=False,
        )

    if playlist_id is not None:
        async def analisar_esta() -> str:
            return await analisar_playlist(playlist_id)

        return [
            Tool(
                name="analisar_esta_playlist",
                description=(
                    "Analisa a playlist que o usuário está vendo: gêneros, "
                    "subgêneros, artistas mais frequentes e uma amostra das "
                    "faixas com suas tags. Chame antes de responder qualquer "
                    "pergunta sobre ela."
                ),
                parameters={"type": "object", "properties": {}, "required": []},
                run=analisar_esta,
            )
        ]

    return [
        Tool(
            name="visao_geral",
            description=(
                "Panorama da coleção numa chamada só: analisa várias playlists em "
                "paralelo e devolve o ranking de gêneros somado mais o gênero "
                "principal de cada uma. Use SEMPRE que a pergunta for ampla ('meu "
                "gosto', 'minhas playlists no geral', 'gênero dominante'), em vez "
                "de chamar analisar_playlist várias vezes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "limite": {
                        "type": "integer",
                        "description": f"Quantas playlists analisar (1 a {MAX_OVERVIEW}). Padrão 5.",
                    }
                },
                "required": [],
            },
            run=visao_geral,
        ),
        Tool(
            name="listar_playlists",
            description=(
                "Lista as playlists do usuário no Spotify, com id, nome e número de "
                "faixas. Use primeiro, para descobrir qual playlist o usuário quer e "
                "pegar o id para as outras ferramentas."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            run=listar_playlists,
        ),
        Tool(
            name="analisar_playlist",
            description=(
                "Analisa os gêneros de uma playlist: distribuição de gêneros e "
                "subgêneros, artistas mais frequentes e uma amostra das faixas com "
                "suas tags. Operação custosa (consulta Spotify e Last.fm faixa a "
                "faixa) — use só nas playlists relevantes para a pergunta."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "playlist_id": {
                        "type": "string",
                        "description": "O id da playlist, obtido em listar_playlists.",
                    }
                },
                "required": ["playlist_id"],
            },
            run=analisar_playlist,
        ),
        # Ponto de extensão: buscar_faixas(...), recomendar(...) entram aqui.
    ]


SYSTEM_PROMPT = """Você é o assistente do Playlist Classifier, um app que analisa \
o gosto musical do usuário a partir das playlists dele no Spotify.

Responda sempre em português do Brasil, de forma direta e conversacional.

Como trabalhar:
- Use as ferramentas para buscar dados reais antes de responder qualquer coisa \
sobre as playlists do usuário. Nunca invente nomes de playlist, faixas, artistas \
ou números.
- Se precisar analisar uma playlist, chame `analisar_playlist`. A análise é \
custosa, então analise só as playlists relevantes para a pergunta.
- Os gêneros vêm de tags da comunidade do Last.fm, não do Spotify. São \
aproximados: trate-os como indício, não como verdade absoluta, e diga isso quando \
for relevante.
- Se as ferramentas não trouxerem dado suficiente para responder, diga o que \
faltou em vez de especular.
- Em perguntas amplas ("minhas playlists no geral"), NÃO analise todas: escolha \
até 4 que representem bem a coleção, analise-as e diga na resposta quais você \
usou. Uma resposta honesta sobre uma amostra vale mais do que esgotar o limite \
de chamadas sem responder nada.
- Quando for analisar várias playlists, peça todas as chamadas de uma vez, no \
mesmo turno — elas rodam em paralelo. Uma por vez é muito mais lento.

Sobre o tom: você pode ter opinião sobre música e comentar padrões interessantes \
que aparecerem nos dados, mas fundamente no que as ferramentas retornaram."""


PLAYLIST_SYSTEM_PROMPT = """Você é o assistente do Playlist Classifier e está respondendo sobre UMA playlist específica, que o usuário tem aberta na tela.

Responda sempre em português do Brasil, de forma direta e conversacional.

Como trabalhar:
- Chame `analisar_esta_playlist` antes de responder qualquer coisa sobre o conteúdo dela. Nunca invente faixas, artistas ou números.
- Você só tem acesso a esta playlist. Se o usuário perguntar sobre outras ou sobre a coleção inteira, diga que aqui o assunto é só esta playlist e sugira a aba Chat, que enxerga todas.
- Os gêneros vêm de tags da comunidade do Last.fm, não do Spotify. São aproximados: trate-os como indício, não como verdade absoluta.
- A análise traz uma amostra das faixas, não todas — não conclua que uma faixa não existe só porque não apareceu na amostra.

Sobre o tom: pode ter opinião sobre música e apontar padrões interessantes, mas fundamente no que a ferramenta retornou."""
