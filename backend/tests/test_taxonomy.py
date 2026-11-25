"""A classificação de gênero: normalização, hierarquia, peso e desempate.

Tudo aqui é offline — `taxonomy.classify` é função pura sobre tags. O conjunto
dourado (`evals/genre_golden.yaml`) mede a precisão em faixas reais; estes
testes travam as REGRAS que produzem aquele número.
"""
import pytest

from app import taxonomy
from app.taxonomy import Tag


# ── normalização ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "escrito, esperado",
    [
        ("Hip-Hop", "hip hop"),
        ("hip_hop", "hip hop"),
        ("  HIP   HOP  ", "hip hop"),
        ("Forró", "forro"),
        ("música brasileira", "musica brasileira"),
        ("R&B", "r b"),
        ("drum & bass", "drum bass"),
        ("", ""),
    ],
)
def test_normalizacao_junta_grafias(escrito, esperado):
    assert taxonomy.normalize(escrito) == esperado


def test_grafias_diferentes_resolvem_para_o_mesmo_genero():
    """O caso que dividia o acervo: 183 faixas em "hip-hop" e 59 em "hip hop"."""
    nos = {taxonomy.resolve(t) for t in ["hip-hop", "hip hop", "Hip-Hop", "HIP_HOP", "rap"]}
    assert nos == {taxonomy.Node("hip-hop", None)}


def test_acento_nao_cria_genero_novo():
    assert taxonomy.resolve("forró") == taxonomy.resolve("forro")


# ── o que não é gênero ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "tag",
    [
        "brasil", "brazilian", "german", "israeli", "usa",      # país
        "seen live", "my top songs", "albums i own",            # comportamento
        "awesome", "sexy", "chill",                             # juízo
        "guitar", "instrumental", "female vocalists",            # instrumentação
        "singer-songwriter",                                     # papel, não estilo
        "alternative", "progressive", "hardcore",                # ambíguo sozinho
        "jay-z", "iboga records",                                # artista, gravadora
        "80s", "90s", "2010s", "1997", "70's",                   # tempo
    ],
)
def test_tag_que_nao_e_genero_e_descartada(tag):
    assert taxonomy.resolve(tag) is None
    assert taxonomy.load().discarded(tag) is True


def test_descartada_e_desconhecida_sao_coisas_diferentes():
    """A diferença é o que vira fila de trabalho: "brasil" foi decidido, e
    "vaporwave" é gênero de verdade que ainda falta no YAML."""
    tabela = taxonomy.load()
    assert tabela.discarded("brasil") is True
    assert tabela.discarded("vaporwave") is False
    assert taxonomy.resolve("vaporwave") is None

    resultado = taxonomy.classify(artist_tags=[Tag("vaporwave", 100)])
    assert resultado.genre is None
    assert resultado.unresolved == ["vaporwave"]


def test_faixa_so_com_ruido_nao_recebe_genero():
    resultado = taxonomy.classify(
        artist_tags=[Tag("brasil", 100), Tag("female vocalists", 90), Tag("seen live", 80)]
    )
    assert resultado == taxonomy.EMPTY


# ── hierarquia ───────────────────────────────────────────────────────────────


def test_subgenero_aponta_para_o_pai():
    assert taxonomy.resolve("minimal techno") == taxonomy.Node("techno", "minimal techno")
    assert taxonomy.resolve("classic rock") == taxonomy.Node("rock", "classic rock")
    assert taxonomy.resolve("sertanejo") == taxonomy.Node("brasileiro", "sertanejo")


def test_filho_pontua_o_pai_uma_vez():
    """O bug central do gráfico antigo: "rock", "classic rock" e "hard rock"
    eram três rótulos com um voto cada, e rock liderava por soma de sinônimos."""
    resultado = taxonomy.classify(
        artist_tags=[Tag("rock", 100), Tag("classic rock", 95), Tag("hard rock", 90)]
    )
    assert resultado.genre == "rock"
    assert resultado.subgenre == "classic rock"
    assert resultado.genres == ["rock"]
    assert resultado.confidence == 1.0


def test_psytrance_nao_e_diluido_em_trance():
    """Decisão de modelagem: no acervo desta conta psytrance é identidade
    própria, não um subgênero de trance (`taxonomy.yaml` explica por quê)."""
    assert taxonomy.resolve("psytrance") == taxonomy.Node("psytrance", None)
    assert taxonomy.resolve("goa") == taxonomy.Node("psytrance", "goa trance")
    assert taxonomy.resolve("progressive trance") == taxonomy.Node("trance", "progressive trance")


# ── peso ─────────────────────────────────────────────────────────────────────


def test_peso_decide_entre_dois_generos():
    """Sem peso, "rock" e "techno" valeriam igual e o resultado sairia alfabético."""
    assert taxonomy.classify(artist_tags=[Tag("rock", 100), Tag("techno", 10)]).genre == "rock"
    assert taxonomy.classify(artist_tags=[Tag("rock", 10), Tag("techno", 100)]).genre == "techno"


def test_tag_sem_peso_vale_o_padrao():
    """Tags gravadas antes da taxonomia são só o nome; continuam classificando."""
    assert taxonomy.classify(artist_tags=["psytrance", "goa"]).genre == "psytrance"


def test_familia_com_duas_tags_ganha_de_uma_tag_mais_forte():
    """"techno" + "minimal" (130) passa "house" (100). É a mesma regra da
    hierarquia, e está registrada no conjunto dourado (rocksted-want-you)."""
    resultado = taxonomy.classify(
        artist_tags=[Tag("house", 100), Tag("techno", 70), Tag("minimal", 60)]
    )
    assert resultado.genre == "techno"


def test_tag_da_faixa_pesa_mais_que_a_do_artista():
    """A tag da faixa descreve a faixa; a do artista, a carreira dele."""
    resultado = taxonomy.classify(
        artist_tags=[Tag("rock", 100)], track_tags=[Tag("techno", 100)]
    )
    assert resultado.genre == "techno"
    assert taxonomy.TRACK_SHARE > taxonomy.ARTIST_SHARE


def test_artista_decide_quando_a_faixa_nao_tem_tag():
    """O caso mais comum no acervo real: `track.getTopTags` volta vazio."""
    resultado = taxonomy.classify(artist_tags=[Tag("psytrance", 100)], track_tags=[])
    assert resultado.genre == "psytrance"
    # Sem penalizar a confiança só porque um dos lados não existia.
    assert resultado.confidence == 1.0


def test_ruido_de_outro_artista_nao_leva_a_faixa():
    """Colaboração de três artistas em que um deles tem tag de metalcore."""
    resultado = taxonomy.classify(
        artist_tags=[
            Tag("psytrance", 100), Tag("goa", 70), Tag("trance", 60),
            Tag("techno", 30), Tag("metalcore", 10),
        ]
    )
    assert resultado.genre == "psytrance"
    assert "metal" not in resultado.genres


# ── determinismo e explicação ────────────────────────────────────────────────


def test_empate_resolve_sempre_igual():
    """Sem regra fixa, a mesma faixa mudaria de gênero entre duas execuções."""
    tags = [Tag("techno", 100), Tag("house", 100)]
    assert taxonomy.classify(artist_tags=tags).genre == "house"
    assert taxonomy.classify(artist_tags=list(reversed(tags))).genre == "house"


def test_confianca_cai_quando_as_tags_discordam():
    concordam = taxonomy.classify(artist_tags=[Tag("techno", 100), Tag("minimal techno", 90)])
    discordam = taxonomy.classify(artist_tags=[Tag("techno", 100), Tag("reggae", 90)])
    assert concordam.confidence == 1.0
    assert discordam.confidence < 0.7


def test_evidencia_cita_as_tags_que_elegeram_o_genero():
    resultado = taxonomy.classify(
        artist_tags=[Tag("thrash metal", 100), Tag("heavy metal", 90), Tag("brasil", 80)]
    )
    assert resultado.genre == "metal"
    assert resultado.evidence == ["thrash metal", "heavy metal"]
    assert len(resultado.evidence) <= taxonomy.MAX_EVIDENCE


def test_evidencia_nao_repete_a_mesma_tag():
    resultado = taxonomy.classify(
        artist_tags=[Tag("psytrance", 100)], track_tags=[Tag("Psytrance", 100)]
    )
    assert [t.lower() for t in resultado.evidence] == ["psytrance"]


# ── integridade do YAML ──────────────────────────────────────────────────────


def test_nenhum_genero_esta_tambem_na_lista_de_descarte():
    """Um rótulo nas duas listas seria decidido pela ordem de carga, não pelo
    YAML — e o descarte vence, apagando um gênero sem aviso."""
    tabela = taxonomy.load()
    conflitos = {chave for chave in tabela.index if chave in tabela.ignored}
    assert conflitos == set()


def test_nenhum_padrao_de_descarte_apaga_um_genero():
    tabela = taxonomy.load()
    apagados = [
        chave for chave in tabela.index if any(p.search(chave) for p in tabela.patterns)
    ]
    assert apagados == []


def test_todo_subgenero_tem_nome_proprio():
    """Subgênero com o mesmo nome do pai faria os dois gráficos repetirem o
    rótulo — era exatamente o remendo que a taxonomia substituiu."""
    tabela = taxonomy.load()
    for chave, no in tabela.index.items():
        if no.subgenre is not None:
            assert taxonomy.normalize(no.subgenre) != taxonomy.normalize(no.genre), chave
